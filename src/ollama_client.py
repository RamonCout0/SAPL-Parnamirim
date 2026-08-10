"""Cliente Ollama - roda na maquina, sem mandar nada para fora.

O Ollama e OPCIONAL. Ele nao decide nenhum campo que va para o SAPL (ver
abaixo), so preenche colunas de sugestao do glossario. Rodar o pipeline com
--sem-ollama produz exatamente o mesmo conjunto de indicacoes prontas, o que
tambem significa que nao ha exigencia de GPU: sem placa, o Ollama cai para CPU
e fica mais lento, e sem Ollama nenhum o resultado nao muda.


O modelo NAO decide sozinho o que vai para o SAPL. Ele faz tres trabalhos
estreitos, e em todos eles o resultado passa por uma verificacao mecanica
antes de ser aceito:

  1. limpar_ementa()        - conserta o portugues estragado pelo OCR SEM
                              inventar conteudo. Se ele acrescentar palavra
                              que nao existia no original, a limpeza e
                              descartada e fica a ementa crua.
  2. achar_ementa()         - quando o OCR comeu o verbo, localiza o objeto
                              do pedido dentro do texto. Retorna trecho que
                              precisa existir literalmente no texto.
  3. escolher_autor()       - casa o nome civil ("Ana Carolina Carvalho de
                              Lima Pires") com o nome do select do SAPL
                              ("Carol Pires"). So aceita ID que esta na lista.

Como o documento e oficial, qualquer resposta que nao passe na verificacao
manda a indicacao para revisao manual em vez de arriscar.
"""
from __future__ import annotations

import json
import re
import unicodedata

import requests

from .config import OLLAMA_MODEL, OLLAMA_URL

TIMEOUT = 180


class OllamaIndisponivel(RuntimeError):
    pass


def esta_no_ar() -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except requests.RequestException:
        return False


def modelos_instalados() -> list[str]:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException:
        return []


def _chat(
    sistema: str,
    usuario: str,
    formato_json: bool = True,
    temperatura: float = 0.0,
    num_ctx: int = 4096,
) -> str:
    """Uma rodada de chat. temperatura 0 para o resultado ser reproduzivel."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": sistema},
            {"role": "user", "content": usuario},
        ],
        "stream": False,
        "options": {
            "temperature": temperatura,
            "num_ctx": num_ctx,
            "num_predict": 700,
        },
    }
    if formato_json:
        payload["format"] = "json"

    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        raise OllamaIndisponivel(str(e)) from e
    return r.json()["message"]["content"]


def _json_ou_none(bruto: str) -> dict | None:
    try:
        return json.loads(bruto)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", bruto, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


# --------------------------------------------------------------------------- #
# verificacao anti-invencao
# --------------------------------------------------------------------------- #

def _palavras(texto: str) -> set[str]:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )
    return {p for p in re.findall(r"[a-z0-9]+", sem_acento) if len(p) > 3}


def _inventou(original: str, reescrito: str, tolerancia: float = 0.12) -> bool:
    """True se o texto reescrito trouxe palavras de conteudo que nao existiam.

    Uma folga pequena e necessaria porque o modelo conserta grafia ("escoldr"
    -> "escolar"), o que legitimamente cria palavra nova.
    """
    orig, novo = _palavras(original), _palavras(reescrito)
    if not novo:
        return True
    novas = novo - orig
    return len(novas) / len(novo) > tolerancia


# --------------------------------------------------------------------------- #
# 1. limpeza da ementa
# --------------------------------------------------------------------------- #

SIS_LIMPAR = """Você corrige texto extraído por OCR de documentos oficiais da Câmara Municipal de Parnamirim.

REGRAS ABSOLUTAS:
- Conserte APENAS erros de OCR: letras trocadas, palavras quebradas, espaços errados, pontuação.
- NUNCA acrescente informação. NUNCA remova informação. NUNCA resuma.
- Não invente nomes de ruas, bairros, números, secretarias ou datas que não estejam no texto.
- Se um trecho estiver ilegível demais, deixe-o exatamente como está.
- Devolva o texto num único parágrafo, sem quebras de linha.

Responda só com JSON: {"ementa": "<texto corrigido>", "ilegivel": true|false}"""


def limpar_ementa(ementa_crua: str) -> dict:
    """Retorna {ementa, alterada, ilegivel, motivo}."""
    if not ementa_crua.strip():
        return {"ementa": "", "alterada": False, "ilegivel": True, "motivo": "vazia"}

    bruto = _chat(SIS_LIMPAR, f"Texto do OCR:\n\n{ementa_crua}")
    dados = _json_ou_none(bruto)
    if not dados or not isinstance(dados.get("ementa"), str):
        return {
            "ementa": ementa_crua,
            "alterada": False,
            "ilegivel": False,
            "motivo": "resposta do modelo nao era JSON valido",
        }

    limpa = re.sub(r"\s+", " ", dados["ementa"]).strip()
    if not limpa:
        return {"ementa": ementa_crua, "alterada": False, "ilegivel": True,
                "motivo": "modelo devolveu vazio"}

    if _inventou(ementa_crua, limpa):
        return {
            "ementa": ementa_crua,
            "alterada": False,
            "ilegivel": False,
            "motivo": "modelo acrescentou conteudo - limpeza descartada",
        }

    # Encurtar demais tambem e sinal de que resumiu em vez de corrigir.
    if len(limpa) < len(ementa_crua) * 0.6:
        return {
            "ementa": ementa_crua,
            "alterada": False,
            "ilegivel": False,
            "motivo": "modelo encurtou o texto - limpeza descartada",
        }

    return {
        "ementa": limpa,
        "alterada": limpa != ementa_crua.strip(),
        "ilegivel": bool(dados.get("ilegivel")),
        "motivo": "ok",
    }


# --------------------------------------------------------------------------- #
# 2. achar a ementa quando o OCR comeu o verbo
# --------------------------------------------------------------------------- #

SIS_ACHAR = """Você lê INDICAÇÕES da Câmara Municipal de Parnamirim extraídas por OCR.

A ementa é o OBJETO DO PEDIDO: o que o vereador pede ao Executivo. Ela começa
depois do verbo (INDICA / REITERA / VEM INDICAR) e termina antes da palavra
"Justificativa".

REGRAS ABSOLUTAS:
- COPIE o trecho literalmente do texto. Não reescreva, não resuma, não complete.
- Não inclua a justificativa, o rodapé, o endereço da Câmara nem carimbos.
- Se não conseguir localizar o pedido com certeza, devolva ementa vazia.

Responda só com JSON: {"ementa": "<trecho copiado>", "achou": true|false}"""


def achar_ementa(texto_bloco: str) -> dict:
    """Fallback para quando o regex nao acha o verbo. Retorna {ementa, achou, motivo}."""
    recorte = texto_bloco[:3500]
    bruto = _chat(SIS_ACHAR, f"Texto da indicação:\n\n{recorte}", num_ctx=6144)
    dados = _json_ou_none(bruto)
    if not dados or not dados.get("achou") or not isinstance(dados.get("ementa"), str):
        return {"ementa": "", "achou": False, "motivo": "modelo nao localizou"}

    ementa = re.sub(r"\s+", " ", dados["ementa"]).strip()
    if len(ementa) < 30:
        return {"ementa": "", "achou": False, "motivo": "trecho curto demais"}

    # Tem de ser copia, nao criacao: exigimos que as palavras existam no texto.
    if _inventou(recorte, ementa, tolerancia=0.05):
        return {"ementa": "", "achou": False,
                "motivo": "trecho nao confere com o texto original"}

    return {"ementa": ementa, "achou": True, "motivo": "ok"}


# --------------------------------------------------------------------------- #
# 3. casar o autor com o select do SAPL
# --------------------------------------------------------------------------- #

# Este prompt recebe uma LISTA CURTA (3 candidatos), nao os 32 parlamentares.
#
# A diferenca e decisiva e foi medida: com a lista inteira, o qwen2.5:3b
# devolvia sempre o mesmo id (o ultimo da lista) e dizia "certeza alta" -
# inclusive para um nome inventado. Com 3 opcoes ele acerta os casos de OCR
# corrompido ("EdéV Rodrigues Queiroz" -> Eder Queiroz, "Gustauo N.gócio d.e.
# FrPita" -> Gustavo Negócio) e recusa corretamente o que nao da para saber.
SIS_AUTOR = """Você identifica vereadores da Câmara Municipal de Parnamirim (RN).

O nome no documento foi lido por OCR de um papel escaneado e pode ter letras
erradas, trocadas ou faltando. Escolha, entre as poucas opções dadas, a que se
refere à MESMA PESSOA.

Nomes civis correspondem a nomes políticos:
- "Ana Carolina Carvalho de Lima Pires" é "Carol Pires"
- "Wolney Freitas de Azevedo França" é "Wolney França"

REGRAS ABSOLUTAS:
- Responda com um dos ids listados, ou 0 se nenhum servir ou se houver dúvida.
- Não invente nomes nem ids.

Responda só com JSON: {"id": <numero>, "certeza": "alta"|"media"|"baixa"}"""


def escolher_autor(
    nome_documento: str, apelido: str, candidatos: list[dict]
) -> dict:
    """candidatos: lista CURTA [{id, nome}]. Retorna {id, nome, certeza, motivo}."""
    if not nome_documento and not apelido:
        return {"id": 0, "nome": "", "certeza": "baixa", "motivo": "sem nome no texto"}
    if not candidatos:
        return {"id": 0, "nome": "", "certeza": "baixa", "motivo": "sem candidatos"}

    lista = "\n".join(f"{c['id']} = {c['nome']}" for c in candidatos)
    assinatura = nome_documento + (f" ({apelido})" if apelido else "")
    bruto = _chat(
        SIS_AUTOR,
        f"Nome no documento (OCR): {assinatura}\n\nOpções:\n{lista}\n0 = nenhuma",
        num_ctx=2048,
    )
    dados = _json_ou_none(bruto)
    if not dados:
        return {"id": 0, "nome": "", "certeza": "baixa",
                "motivo": "resposta do modelo nao era JSON"}

    try:
        escolhido = int(dados.get("id", 0))
    except (TypeError, ValueError):
        escolhido = 0

    validos = {c["id"]: c["nome"] for c in candidatos}
    if escolhido == 0:
        return {"id": 0, "nome": "", "certeza": "baixa",
                "motivo": "modelo respondeu 'nenhuma das opcoes'"}
    if escolhido not in validos:
        return {"id": 0, "nome": "", "certeza": "baixa",
                "motivo": f"id {escolhido} nao estava entre os candidatos"}

    return {
        "id": escolhido,
        "nome": validos[escolhido],
        "certeza": str(dados.get("certeza", "media")).lower(),
        "motivo": "ok",
    }
