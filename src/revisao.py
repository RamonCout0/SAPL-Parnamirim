"""Revisao manual: o que o OCR nao entregou com seguranca sai como imagem.

O documento e oficial, entao nao existe "chute aceitavel". Toda indicacao que
nao passar nos criterios de confianca vai para output/revisao_manual/:

  - a pagina renderizada em PNG, legivel, para conferir com o olho
  - uma linha no glossario.csv com o que a maquina conseguiu ler e as colunas
    para voce escrever a versao correta - E' O ARQUIVO QUE VOCE EDITA, mas
    abra num programa de planilha (Excel/LibreOffice): um CSV de texto
    corrido, num editor de codigo, fica uma linha so gigante
  - REVISAO.md, so para LEITURA: o mesmo conteudo do glossario, mas um bloco
    por indicacao com as imagens incorporadas - abra o preview de Markdown do
    editor para ver tudo formatado e com a pagina ao lado do texto

ONDE O SEU TRABALHO FICA GUARDADO
---------------------------------
Em config/correcoes.json, nao no CSV.

O glossario.csv e regenerado a cada rodada do pipeline (as pendentes mudam
conforme voce resolve), entao ele NAO pode ser a memoria do sistema. Antes,
era - e o resultado e que toda correcao digitada era apagada na rodada
seguinte: a indicacao resolvida saia da lista de pendentes, a linha dela
sumia do CSV, e na rodada seguinte a ementa voltava a ser a que a maquina
tinha lido. A indicacao voltava para revisao para sempre.

Agora o CSV e so uma JANELA para as pendentes: e regravado ja preenchido com
o que voce digitou antes, e tudo que voce escreve nele e importado para o
correcoes.json antes de qualquer coisa ser reescrita. O correcoes.json e
permanente e versionavel, do mesmo jeito que o aliases_aprendidos.json - uma
correcao so precisa ser feita uma vez, por uma pessoa.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from .config import CONFIG_DIR

# Colunas que VOCE preenche. O resto e informativo.
#
# CONFIRMAR existe para os motivos que NAO tem nada para digitar: "numero
# deduzido pela sequencia" ou "bloco com 1 pagina" nao sao erro de ementa nem
# de autor - sao avisos estruturais. Preencher EMENTA_MANUAL/AUTOR_ID_MANUAL
# nesses casos nao adianta nada, porque o motivo que esta bloqueando e outro.
# Escreva "sim" em CONFIRMAR para dizer "eu vi a pagina, esta tudo certo assim
# mesmo".
COLUNAS_MANUAIS = ["NUMERO_MANUAL", "EMENTA_MANUAL", "AUTOR_ID_MANUAL", "CONFIRMAR"]

# Ordem pensada para quem abre o CSV bruto (nao no Excel): as colunas que voce
# de fato edita ficam logo no comeco da linha, antes dos textos longos
# (ementa lida, sugestao do modelo) que empurrariam tudo para fora da tela.
#
# "precisa" diz QUAIS das tres colunas manuais resolvem esta linha especifica
# (ementa / autor / confirmar). Sem isso, a tela de revisao tinha de adivinhar
# pelo texto do motivo, e adivinhava errado: considerava a linha resolvida
# assim que UMA das tres fosse preenchida, entao uma indicacao a que faltava
# ementa E autor sumia da fila depois de so meia correcao.
CABECALHO_GLOSSARIO = [
    # "numero" e sempre o numero LIDO pelo OCR, mesmo quando voce ja corrigiu:
    # e a chave que reencontra a correcao na rodada seguinte, quando o OCR ler
    # o mesmo numero errado de novo. O numero certo fica em NUMERO_MANUAL.
    "numero",
    "ano",
    "paginas",
    "NUMERO_MANUAL",
    "DATA_MANUAL",
    "EMENTA_MANUAL",
    "AUTOR_ID_MANUAL",
    "CONFIRMAR",
    "precisa",
    "data_lida_pela_maquina",
    "motivo",
    "autor_lido_pela_maquina",
    "sugestao_ollama_autor",
    "ementa_lida_pela_maquina",
    "sugestao_ollama_ementa",
    "imagens",
]

# Memoria permanente das correcoes. Fica em config/ (e nao em output/) porque
# e trabalho humano, nao resultado de processamento: sobrevive a qualquer
# rodada do pipeline e pode ser versionado no git, valendo para todo mundo que
# usa o repositorio - o mesmo raciocinio do aliases_aprendidos.json.
CORRECOES = CONFIG_DIR / "correcoes.json"

_DOC_CORRECOES = (
    "Correcoes manuais das indicacoes, por 'numero/ano'. Este arquivo e a "
    "memoria permanente da revisao: o glossario.csv e regenerado a cada "
    "rodada, este aqui nunca e. O que estiver aqui vence qualquer deducao da "
    "maquina. Pode versionar no git - uma correcao feita por uma pessoa passa "
    "a valer para todas."
)


def ler_correcoes(caminho: Path | None = None) -> dict[str, dict]:
    """Correcoes permanentes, por "numero/ano". Vazio se o arquivo nao existe."""
    # O caminho e resolvido na CHAMADA, nao no default da assinatura: assim os
    # testes conseguem apontar CORRECOES para uma pasta temporaria sem risco
    # de escrever no arquivo de verdade do usuario.
    caminho = caminho or CORRECOES
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{caminho} esta corrompido ({e}). E o arquivo com as suas "
            "correcoes manuais - conserte o JSON a mao em vez de apagar, "
            "senao o trabalho de revisao se perde."
        ) from e
    return dados.get("correcoes", {})


def gravar_correcoes(correcoes: dict[str, dict], caminho: Path | None = None) -> None:
    caminho = caminho or CORRECOES
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(
            {"_doc": _DOC_CORRECOES, "correcoes": correcoes},
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def registrar_correcao(
    identificador: str,
    *,
    numero: int | None = None,
    data: str | None = None,
    ementa: str | None = None,
    autor_id: int | None = None,
    confirmado: bool | None = None,
    caminho: Path | None = None,
) -> None:
    """Grava UMA correcao, preservando o que ja estava la.

    None significa "nao mexer neste campo" - so quem foi passado e alterado.
    Isso deixa a tela de revisao salvar so a ementa sem apagar o autor que ja
    tinha sido resolvido numa passagem anterior.
    """
    caminho = caminho or CORRECOES
    correcoes = ler_correcoes(caminho)
    item = dict(correcoes.get(identificador, {}))
    if numero is not None:
        item["numero"] = int(numero)
    if data is not None:
        if data.strip():
            item["data"] = data.strip()
        else:
            item.pop("data", None)
    if ementa is not None:
        if ementa.strip():
            item["ementa"] = ementa.strip()
        else:
            item.pop("ementa", None)
    if autor_id is not None:
        item["autor_id"] = int(autor_id)
        item.pop("autor_id_invalido", None)
    if confirmado is not None:
        if confirmado:
            item["confirmado"] = True
        else:
            item.pop("confirmado", None)
    item["atualizado_em"] = datetime.now().isoformat(timespec="seconds")

    # Sobrou so o carimbo de data: nao ha correcao nenhuma, tira a entrada em
    # vez de deixar lixo acumulando no arquivo.
    if set(item) <= {"atualizado_em"}:
        correcoes.pop(identificador, None)
    else:
        correcoes[identificador] = item
    gravar_correcoes(correcoes, caminho)


def importar_do_glossario(
    caminho_csv: Path, caminho_json: Path | None = None
) -> int:
    """Puxa para o correcoes.json o que foi digitado no glossario.csv.

    Roda antes de qualquer regravacao do CSV: e o que garante que editar a
    planilha a mao (o caminho "avancado" do README) continua funcionando e
    nunca mais se perde. Devolve quantas entradas foram criadas ou mudadas.
    """
    caminho_json = caminho_json or CORRECOES
    do_csv = ler_glossario(caminho_csv)
    if not do_csv:
        return 0

    correcoes = ler_correcoes(caminho_json)
    mudou = 0
    agora = datetime.now().isoformat(timespec="seconds")
    for identificador, item in do_csv.items():
        atual = dict(correcoes.get(identificador, {}))
        novo = dict(atual)
        for chave in ("numero", "data", "ementa", "autor_id",
                      "autor_id_invalido", "confirmado"):
            if chave in item:
                novo[chave] = item[chave]
        # Autor corrigido depois de um valor invalido: o aviso antigo some.
        if "autor_id" in novo:
            novo.pop("autor_id_invalido", None)
        if {k: v for k, v in novo.items() if k != "atualizado_em"} != {
            k: v for k, v in atual.items() if k != "atualizado_em"
        }:
            novo["atualizado_em"] = agora
            correcoes[identificador] = novo
            mudou += 1

    if mudou:
        gravar_correcoes(correcoes, caminho_json)
    return mudou


def chave_da_correcao(numero, ano, paginas: str = "", ambigua: bool = False) -> str:
    """Onde a correcao desta indicacao fica guardada no correcoes.json.

    Normalmente "numero/ano", o numero LIDO pelo OCR - que nao muda entre
    rodadas e por isso reencontra a correcao na rodada seguinte.

    O problema: numero lido nao e unico. No lote de 2022, duas paginas
    diferentes trazem "INDICAÇÃO N° 706/2022" impresso (a sequencia vai 706,
    707, 706, 709 - o 708 nao existe), entao o arquivo tem DUAS "706". Com a
    chave sendo so o numero, a correcao escrita para uma valia para as duas:
    corrigir "esta aqui e a 708" renumerava tambem a 706 de verdade, e o lote
    terminava com duas 708 - uma delas cadastrada em silencio, porque nada mais
    reclamava dela.

    Quando ha essa disputa, a chave ganha as paginas do bloco (que sao unicas
    por definicao) e as duas passam a ter memoria propria. Quem nao disputa
    nada continua com a chave de sempre, entao nenhuma correcao ja feita se
    perde.
    """
    if ambigua and paginas:
        return f"{numero}/{ano}@{paginas}"
    return f"{numero}/{ano}"


def correcao_de(
    correcoes: dict[str, dict],
    numero,
    ano,
    paginas: str = "",
    ambigua: bool = False,
) -> dict:
    """A correcao desta indicacao. Da chave especifica para a geral.

    Uma indicacao em disputa NUNCA cai na chave geral: aquela entrada serve
    para duas indicacoes diferentes e nao da para saber de quem ela e. Melhor
    a pessoa digitar de novo, uma vez, do que o programa escolher por ela.
    """
    if paginas:
        achada = correcoes.get(f"{numero}/{ano}@{paginas}")
        if achada is not None:
            return achada
    if ambigua:
        return {}
    return correcoes.get(f"{numero}/{ano}", {})


def ambigua_no_glossario(linhas: list[dict], numero, ano) -> bool:
    """Ha mais de uma linha pendente com este mesmo numero lido?

    A tela de conferencia pergunta isto antes de salvar. Ela tem como saber
    porque _marcar_numeros_repetidos manda as DUAS para conferencia - se so uma
    aparecesse aqui, a disputa passaria despercebida bem na hora de gravar.
    """
    return sum(1 for l in linhas
               if l.get("numero") == str(numero) and l.get("ano") == str(ano)) > 1


def identificador_lido(item: dict) -> str:
    """A chave da correcao a partir de uma indicacao ja gravada em
    indicacoes.json - o mesmo que Indicacao.identificador_lido, mas lendo o
    dicionario cru, sem precisar reconstruir o objeto."""
    return f"{item.get('numero_lido') or item.get('numero')}/{item.get('ano')}"


def divergencias_da_correcao(item: dict, correcoes: dict[str, dict]) -> list[str]:
    """O que voce corrigiu e NAO chegou nesta indicacao. Vazio = tudo aplicado.

    A correcao e escrita em config/correcoes.json na hora em que voce salva na
    tela de conferencia, mas quem a aplica na indicacao e o pipeline, na rodada
    seguinte. Entre uma coisa e outra existe uma janela em que o
    output/indicacoes.json ainda mostra o texto velho - e era exatamente esse
    texto velho que o envio levaria para o SAPL.

    Enquanto o envio era manual isso aparecia na tela e a pessoa via. Com o
    envio automatico ninguem ve: por isso a conferencia vale campo a campo,
    aqui, imediatamente antes de cadastrar.
    """
    manual = correcao_de(
        correcoes,
        item.get("numero_lido") or item.get("numero"),
        item.get("ano"),
        f"{item.get('pagina_inicial')}-{item.get('pagina_final')}",
    )
    if not manual:
        return []

    def _texto(valor) -> str:
        return str(valor or "").strip()

    problemas = []
    if manual.get("numero") and int(manual["numero"]) != int(item.get("numero") or 0):
        problemas.append(
            f"o número corrigido é {manual['numero']}, mas esta indicação ainda "
            f"está como {item.get('numero')}")
    if manual.get("data") and _texto(manual["data"]) != _texto(item.get("data_apresentacao")):
        problemas.append(
            f"a data corrigida é {manual['data']}, mas esta indicação ainda "
            f"está com {_texto(item.get('data_apresentacao')) or '(em branco)'}")
    if manual.get("ementa") and _texto(manual["ementa"]) != _texto(item.get("ementa")):
        problemas.append(
            "a ementa que você escreveu na conferência não é a que está aqui")
    if manual.get("autor_id") and int(manual["autor_id"]) != int(item.get("autor_id") or 0):
        problemas.append(
            f"o autor corrigido é o id {manual['autor_id']}, mas esta indicação "
            f"ainda está com o id {item.get('autor_id') or 0}")
    if manual.get("autor_id_invalido"):
        problemas.append(
            f"o autor foi digitado como '{manual['autor_id_invalido']}', que não "
            "é um número de id")
    return problemas


def exportar_paginas_png(
    caminho_pdf: str,
    paginas: list[int],
    destino: Path,
    prefixo: str,
    escala: float = 2.2,
) -> list[str]:
    """Renderiza paginas do PDF em PNG. escala 2.2 ~ 158 dpi, boa para ler."""
    # Import aqui dentro, nao no topo: assim as regras de revisao (o que conta
    # como resolvido, o formato das correcoes) podem ser importadas e testadas
    # sem exigir a biblioteca de renderizar PDF instalada.
    import pypdfium2 as pdfium

    destino.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(caminho_pdf)
    gerados = []
    try:
        for n in paginas:
            pagina = doc[n - 1]
            imagem = pagina.render(scale=escala).to_pil()
            arquivo = destino / f"{prefixo}_pg{n:03d}.png"
            imagem.save(arquivo)
            gerados.append(arquivo.name)
    finally:
        doc.close()
    return gerados


# Qual coluna manual resolve cada exigencia da coluna "precisa".
CAMPO_DE = {
    "numero": "NUMERO_MANUAL",
    "data": "DATA_MANUAL",
    "ementa": "EMENTA_MANUAL",
    "autor": "AUTOR_ID_MANUAL",
    "confirmar": "CONFIRMAR",
}
ROTULO_DE = {
    "numero": "número",
    "data": "data (está no carimbo do verso)",
    "ementa": "ementa",
    "autor": "autor",
    "confirmar": "conferir a página",
}


def linhas_do_glossario(caminho: Path) -> list[dict]:
    """O glossario como lista de linhas cruas, na ordem do arquivo."""
    if not caminho.exists():
        return []
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def precisa_de(linha: dict) -> list[str]:
    """O que ESTA indicacao exige: "ementa", "autor" e/ou "confirmar".

    Vem da coluna "precisa", escrita pelo pipeline a partir dos motivos reais.
    Um glossario gerado pela versao antiga nao tem essa coluna - nesse caso
    deduz do texto do motivo, para o arquivo continuar utilizavel sem precisar
    rodar a extracao de novo.
    """
    bruto = (linha.get("precisa") or "").strip()
    if bruto:
        return [p.strip() for p in bruto.split(",") if p.strip() in CAMPO_DE]

    motivos = (linha.get("motivo") or "").lower()
    deduzido = []
    if "numero:" in motivos:
        deduzido.append("numero")
    if "data:" in motivos:
        deduzido.append("data")
    if "ementa" in motivos:
        deduzido.append("ementa")
    if "autor" in motivos:
        deduzido.append("autor")
    if any(t in motivos for t in ("numero deduzido", "1 pagina", "numero repetido",
                                  "tambem aparece em", "ollama falhou")):
        deduzido.append("confirmar")
    return deduzido or ["confirmar"]


def falta_em(linha: dict) -> list[str]:
    """O que ainda esta faltando nesta linha.

    ERA AQUI O BUG que fazia a revisao "pular" indicacoes: a versao antiga
    considerava a linha resolvida quando QUALQUER um dos tres campos estivesse
    preenchido. Uma indicacao a que faltava ementa E autor sumia da fila
    depois de meia correcao, e continuava indo para revisao em toda rodada do
    pipeline - o usuario via o defeito ser ignorado, sem entender por que.
    """
    return [p for p in precisa_de(linha) if not (linha.get(CAMPO_DE[p]) or "").strip()]


def ja_revisada(linha: dict) -> bool:
    return not falta_em(linha)


def salvar_correcao(
    caminho_glossario: Path,
    numero: str,
    ano: str,
    *,
    paginas: str = "",
    numero_manual: str = "",
    data: str = "",
    ementa: str = "",
    autor_id: str = "",
    confirmado: bool = False,
) -> None:
    """Grava a correcao nos DOIS lugares, na ordem que importa.

    Primeiro no correcoes.json, que e a memoria permanente lida pelo pipeline;
    depois no glossario.csv, que e so a janela desta tela. Se o CSV se perder
    (ele e regravado a cada rodada), o trabalho continua no JSON - era
    exatamente o contrario disso que apagava tudo antes.

    CONFIRMAR O NUMERO LIDO TAMBEM E RESPOSTA
    -----------------------------------------
    Quando a indicacao pede "numero" (o valor lido nao conversa com a sequencia
    do lote, ou dois blocos sairam com o mesmo numero), a pessoa abre a imagem e
    pode chegar a duas conclusoes: "o certo e outro" ou "o certo e esse mesmo".
    As duas resolvem a pendencia.

    A versao antiga so registrava a primeira. Digitar o MESMO numero que ja
    estava la nao gravava nada, a linha continuava faltando "numero" para
    sempre, e a tela de conferencia - que sempre volta para a primeira pendente
    - jogava a pessoa de volta naquela indicacao a cada vez que ela salvava.
    Era o defeito de "sempre volta para a mesma": nao havia jeito de sair dela.
    """
    # "numero" aqui e sempre o LIDO (a chave). Digitar o mesmo valor nao muda o
    # numero, mas CONFIRMA que ele esta certo - o que e uma resposta.
    novo_numero = str(numero_manual).strip()
    mudou_numero = novo_numero.isdigit() and novo_numero != str(numero)

    linhas = linhas_do_glossario(caminho_glossario)
    ambigua = ambigua_no_glossario(linhas, numero, ano)
    # Com duas linhas de mesmo numero, so as paginas dizem qual das duas esta
    # na tela. Sem isto, editar a segunda gravava na primeira - a pessoa
    # digitava o numero certo e ele aparecia na indicacao errada.
    alvo = next(
        (l for l in linhas
         if l.get("numero") == str(numero) and l.get("ano") == str(ano)
         and (not paginas or l.get("paginas") == paginas)),
        None,
    )
    # So conta como confirmacao onde o numero era de fato a pergunta. Em toda
    # indicacao que nao pede numero, digitar o proprio numero nao quer dizer
    # nada e nao pode virar um "ja conferi tudo" implicito.
    confirmou_numero = bool(
        alvo and "numero" in precisa_de(alvo)
        and novo_numero.isdigit() and not mudou_numero
    )

    registrar_correcao(
        chave_da_correcao(numero, ano, paginas or (alvo or {}).get("paginas", ""),
                          ambigua),
        numero=int(novo_numero) if mudou_numero else None,
        data=data,
        ementa=ementa,
        autor_id=int(autor_id) if str(autor_id).strip().isdigit() else None,
        confirmado=confirmado or confirmou_numero,
    )

    if alvo is not None:
        if novo_numero.isdigit():
            # Gravado nos dois casos: e ele que faz a linha contar como
            # resolvida. Numero igual ao lido nao vira correcao no JSON
            # (ler_glossario descarta), so tira a linha da fila.
            alvo["NUMERO_MANUAL"] = novo_numero
        alvo["DATA_MANUAL"] = data
        alvo["EMENTA_MANUAL"] = ementa
        if str(autor_id).strip():
            alvo["AUTOR_ID_MANUAL"] = str(autor_id)
        alvo["CONFIRMAR"] = "sim" if (confirmado or confirmou_numero) else ""
    escrever_glossario(linhas, caminho_glossario)


def escrever_glossario(linhas: list[dict], caminho: Path) -> None:
    """CSV com BOM para o Excel abrir com os acentos certos."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=CABECALHO_GLOSSARIO, delimiter=";")
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({k: linha.get(k, "") for k in CABECALHO_GLOSSARIO})


def escrever_revisao_md(linhas: list[dict], caminho: Path) -> None:
    """Mesmo conteudo do glossario, mas formatado para LER - abra o preview
    de Markdown do editor. A edicao continua sendo feita no glossario.csv;
    isto aqui e so para nao precisar decifrar CSV bruto para saber o que
    cada indicacao precisa.
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    blocos = [
        "# Indicações para revisão manual",
        "",
        f"{len(linhas)} indicação(ões). A edição é feita em `glossario.csv` "
        "(abra num programa de planilha) - preencha `EMENTA_MANUAL` e/ou "
        "`AUTOR_ID_MANUAL` lá. Isto aqui é só para consulta.",
        "",
        "---",
    ]
    for l in linhas:
        blocos += [
            "",
            f"## {l['numero']}/{l['ano']} — página(s) {l['paginas']}",
            "",
            f"**Motivo da revisão:** {l['motivo']}",
            "",
            f"**Falta preencher:** {l.get('precisa') or '—'}",
            "",
            f"**Autor lido pela máquina:** {l['autor_lido_pela_maquina']}",
        ]
        if l.get("sugestao_ollama_autor"):
            blocos.append(f"**Sugestão do modelo:** {l['sugestao_ollama_autor']}")
        blocos += [
            "",
            "**Ementa lida pela máquina:**",
            "",
            f"> {l['ementa_lida_pela_maquina'] or '_(vazia)_'}",
        ]
        if l.get("sugestao_ollama_ementa"):
            blocos += ["", f"**Trecho sugerido pelo modelo:** {l['sugestao_ollama_ementa']}"]
        blocos += ["", "**Página(s) escaneada(s):**", ""]
        for img in (l.get("imagens") or "").split(","):
            img = img.strip()
            if img:
                blocos.append(f"![{img}](imagens/{img})")
        blocos += ["", "---"]

    caminho.write_text("\n".join(blocos) + "\n", encoding="utf-8")


def ler_glossario(caminho: Path) -> dict[str, dict]:
    """Le o glossario preenchido. Ignora linhas em branco.

    A chave e a mesma do correcoes.json (ver chave_da_correcao): "numero/ano",
    ou "numero/ano@paginas" quando duas linhas disputam o mesmo numero lido.
    Sem essa distincao, a segunda linha sobrescrevia a primeira neste
    dicionario e uma das duas correcoes simplesmente sumia na importacao.
    """
    if not caminho.exists():
        return {}
    todas = linhas_do_glossario(caminho)
    preenchidos: dict[str, dict] = {}
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            numero = (linha.get("numero") or "").strip()
            ano = (linha.get("ano") or "").strip()
            if not numero or not ano:
                continue
            ementa = (linha.get("EMENTA_MANUAL") or "").strip()
            autor = (linha.get("AUTOR_ID_MANUAL") or "").strip()
            confirmar = (linha.get("CONFIRMAR") or "").strip()
            num_manual = (linha.get("NUMERO_MANUAL") or "").strip()
            data_manual = (linha.get("DATA_MANUAL") or "").strip()
            if not ementa and not autor and not confirmar and not num_manual \
                    and not data_manual:
                continue
            item: dict = {}
            if data_manual:
                item["data"] = data_manual
            # Digitar o mesmo numero que ja estava lido nao e correcao: evita
            # encher o arquivo de entradas que nao mudam nada.
            if num_manual.isdigit() and num_manual != numero:
                item["numero"] = int(num_manual)
            if ementa:
                item["ementa"] = ementa
            if autor:
                try:
                    item["autor_id"] = int(autor)
                except ValueError:
                    item["autor_id_invalido"] = autor
            if confirmar:
                item["confirmado"] = True
            preenchidos[chave_da_correcao(
                numero, ano, (linha.get("paginas") or "").strip(),
                ambigua_no_glossario(todas, numero, ano))] = item
    return preenchidos


def escrever_referencia_autores(ids: dict, caminho: Path) -> None:
    """Tabela de IDs para consultar enquanto preenche o glossario."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    parlamentares = [a for a in ids["autores"] if a.get("parlamentar")]
    linhas = [
        "# IDs de autor para o glossario",
        "",
        "Use a coluna ID na coluna `AUTOR_ID_MANUAL` do glossario.csv.",
        "Tipo de autor no SAPL e sempre **Parlamentar (2)**.",
        "",
        "| ID | Nome no SAPL |",
        "|---:|--------------|",
    ]
    linhas += [
        f"| {a['id']} | {a['nome']} |"
        for a in sorted(parlamentares, key=lambda x: x["nome"])
    ]
    linhas += [
        "",
        "## Órgãos e comissões (não usar com tipo Parlamentar)",
        "",
        "| ID | Nome no SAPL |",
        "|---:|--------------|",
    ]
    linhas += [
        f"| {a['id']} | {a['nome']} |"
        for a in sorted(
            (a for a in ids["autores"] if not a.get("parlamentar")),
            key=lambda x: x["nome"],
        )
    ]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
