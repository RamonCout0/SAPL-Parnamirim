"""Traz do SAPL a lista COMPLETA de vereadores e atualiza config\\sapl_ids.json.

    .venv\\Scripts\\python scripts\\sincronizar_autores.py
    .venv\\Scripts\\python scripts\\sincronizar_autores.py --simular   nao grava nada

POR QUE ISTO EXISTE
-------------------
O config\\sapl_ids.json foi montado a partir do HTML do formulario de cadastro,
que so mostra os autores validos para a data que estiver na tela. Com a data de
hoje, aparecem 32 parlamentares - os das legislaturas atuais. Os vereadores das
legislaturas antigas simplesmente nao estavam no arquivo.

Medido em 26/08/2026 contra a API do SAPL: a Camara tem 56 parlamentares
cadastrados, e 26 deles faltavam. O efeito no lote de 2010 foi este: de 426
indicacoes, 386 ficaram sem autor - nao porque o programa nao conseguiu LER o
nome (leu 418 de 426, 98%), mas porque o nome lido nao existia no catalogo. O
programa entao oferecia o vizinho mais parecido como "melhor palpite", e o
palpite era outra pessoa: "Katia Carvalho de Lima" virava "Carol Pires" com
escore 84, a cinco pontos do limite de aceite automatico.

O QUE A API ENTREGA DE GRACA
----------------------------
Cada parlamentar vem com `nome_parlamentar` (o nome politico, que o SAPL usa) e
`nome_completo` (o nome civil, que e como o vereador assina o papel). Esse par e
exatamente o glossario que vinha sendo montado a mao, uma confirmacao por vez.

VEREADOR SEM CADASTRO DE AUTOR
------------------------------
"Parlamentar" e "Autor" sao tabelas diferentes no SAPL. Ha vereador que existe
como parlamentar mas nunca ganhou registro de Autor - e sem esse registro ele
NAO aparece no select do formulario, em data nenhuma. Na 13a legislatura
(2009-2012) isso vale para 11 dos 12 vereadores.

Esses entram no catalogo com id 0 e a marca `sem_cadastro_no_sapl`. Servem para
o programa RECONHECER a assinatura e dizer o motivo certo - "fulano assinou, mas
nao tem cadastro de Autor no SAPL" - em vez de apontar um homonimo qualquer.
Cadastrar o Autor no SAPL e trabalho de tela, feito uma vez por vereador; depois
basta rodar este script de novo.

Aliases que voce confirmou a mao NUNCA sao removidos - so recebem companhia.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

# requests, e nao urllib: medido em 26/08/2026 nesta maquina, urllib.request
# estoura WinError 10060 (timeout de conexao) contra o host do SAPL enquanto
# requests responde na hora. E a mesma biblioteca que o resto do projeto ja usa.
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.config import CONFIG_DIR

BASE = "https://sapl.parnamirim.rn.leg.br/api"
TIMEOUT = 60

# content_type 2 = Parlamentar. E o que liga um registro de Autor a um
# parlamentar de verdade, via object_id.
CT_PARLAMENTAR = 2


def _normalizar(s: str) -> str:
    s = "".join(
        c for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(s.split())


def _pegar(url: str, tentativas: int = 4) -> dict:
    """GET com repeticao.

    O host do SAPL derruba conexao no meio de uma sequencia de chamadas - aqui
    ele parou na pagina 8 de `mandato` com timeout, depois de servir as sete
    anteriores sem reclamar. Uma pausa curta e outra tentativa resolvem; sem
    isso o script desiste no meio e o catalogo nunca chega a ser atualizado.
    """
    espera = 3
    for tentativa in range(1, tentativas + 1):
        try:
            r = requests.get(
                url, headers={"Accept": "application/json"}, timeout=TIMEOUT
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if tentativa == tentativas:
                raise
            print(f"    (tentativa {tentativa} falhou: {type(e).__name__}; "
                  f"repetindo em {espera}s)")
            time.sleep(espera)
            espera *= 2
    raise RuntimeError("inalcancavel")


def _buscar_tudo(rota: str) -> list[dict]:
    """Percorre todas as paginas de uma rota da API.

    A API do SAPL nao devolve `count` util e ignora `o=-id` (ver as notas da
    instancia), entao a paginacao e seguida pelo proprio `next_page`.
    """
    itens: dict[int, dict] = {}
    pagina = 1
    while True:
        url = f"{BASE}/{rota}/?limit=50&page={pagina}"
        dados = _pegar(url)
        for x in dados.get("results", []):
            itens[x["id"]] = x
        prox = dados.get("pagination", {}).get("next_page")
        if not prox:
            break
        pagina = prox
    return list(itens.values())


def _rotulo_legislatura(leg: dict) -> str:
    ini = (leg.get("data_inicio") or "")[:4]
    fim = (leg.get("data_fim") or "")[:4]
    return f"{leg.get('numero')}a ({ini}-{fim})"


def main() -> int:
    simular = "--simular" in sys.argv
    destino = CONFIG_DIR / "sapl_ids.json"

    print("Lendo o SAPL ...")
    try:
        parlamentares = _buscar_tudo("parlamentares/parlamentar")
        autores = _buscar_tudo("base/autor")
        mandatos = _buscar_tudo("parlamentares/mandato")
        legislaturas = _buscar_tudo("parlamentares/legislatura")
    except Exception as e:
        # Rede fora do ar nao pode virar catalogo pela metade: sai sem gravar.
        print(f"ERRO ao falar com o SAPL: {e}")
        print("Nada foi alterado em config\\sapl_ids.json.")
        return 1

    print(f"  {len(parlamentares)} parlamentares | {len(autores)} autores | "
          f"{len(mandatos)} mandatos")

    leg_por_id = {l["id"]: _rotulo_legislatura(l) for l in legislaturas}
    legs_do_parlamentar: dict[int, set[str]] = {}
    for m in mandatos:
        rotulo = leg_por_id.get(m.get("legislatura"))
        if rotulo:
            legs_do_parlamentar.setdefault(m["parlamentar"], set()).add(rotulo)

    # Autor -> parlamentar. Dois caminhos, nesta ordem:
    #   1. object_id, quando o registro de Autor aponta para o parlamentar;
    #   2. nome, para o Autor digitado como texto livre. Aconteceu de verdade
    #      com "Rosano Taveira da Cunha" e "Raimunda Nilda da Silva Cruz":
    #      foram cadastrados com o nome CIVIL, sem vinculo com o parlamentar
    #      (que no SAPL se chama "Taveira" e "Professora Nilda").
    autor_do_parlamentar: dict[int, dict] = {}
    for a in autores:
        if a.get("content_type") == CT_PARLAMENTAR and a.get("object_id"):
            autor_do_parlamentar[a["object_id"]] = a
    soltos = [a for a in autores if not a.get("object_id")]
    for a in soltos:
        for p in parlamentares:
            if p["id"] in autor_do_parlamentar:
                continue
            if _normalizar(p["nome_completo"]) == _normalizar(a["nome"]):
                autor_do_parlamentar[p["id"]] = a

    catalogo = json.loads(destino.read_text(encoding="utf-8"))
    antigos = catalogo["autores"]
    # nome normalizado -> registro ja existente (para nao duplicar ninguem)
    por_nome = {_normalizar(a["nome"]): a for a in antigos}

    novos, enriquecidos, sem_cadastro = [], [], []

    for p in sorted(parlamentares, key=lambda x: x["nome_parlamentar"]):
        politico = (p["nome_parlamentar"] or "").strip()
        civil = (p["nome_completo"] or "").strip()
        if not politico:
            continue
        autor = autor_do_parlamentar.get(p["id"])
        legs = sorted(legs_do_parlamentar.get(p["id"], set()))

        # Ja esta no catalogo? Pode estar pelo nome politico OU pelo civil
        # (os dois casos de texto livre acima).
        reg = por_nome.get(_normalizar(politico)) or por_nome.get(_normalizar(civil))

        if reg is None:
            reg = {
                "id": autor["id"] if autor else 0,
                "nome": politico,
                "parlamentar": True,
                "aliases": [],
            }
            antigos.append(reg)
            por_nome[_normalizar(politico)] = reg
            novos.append(reg)

        # O nome civil e a chave que faz a assinatura do papel casar. Nunca
        # remove alias existente - so acrescenta o que faltava.
        ja = {_normalizar(x) for x in reg.get("aliases", [])}
        ja.add(_normalizar(reg["nome"]))
        for candidato in (civil, politico):
            if candidato and _normalizar(candidato) not in ja:
                reg.setdefault("aliases", []).append(candidato)
                ja.add(_normalizar(candidato))
                if reg not in novos and reg not in enriquecidos:
                    enriquecidos.append(reg)

        if legs:
            reg["legislaturas"] = legs

        if autor:
            # Um id que veio do SAPL vale mais que o que estava no arquivo.
            reg["id"] = autor["id"]
            reg.pop("sem_cadastro_no_sapl", None)
        elif not reg.get("id"):
            reg["sem_cadastro_no_sapl"] = True
            reg["id"] = 0
            sem_cadastro.append(reg)

    catalogo["autores"] = antigos
    catalogo["_autores_sincronizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"\n  novos no catalogo : {len(novos)}")
    for r in novos:
        marca = "  SEM CADASTRO DE AUTOR" if r.get("sem_cadastro_no_sapl") else ""
        print(f"      + {r['nome']:<24} id {r['id']:<4}{marca}")
    print(f"  aliases acrescentados a quem ja existia: {len(enriquecidos)}")

    if sem_cadastro:
        print(f"\n  {len(sem_cadastro)} vereador(es) SEM registro de Autor no SAPL.")
        print("  O programa passa a reconhecer a assinatura deles e a dizer o")
        print("  motivo certo, mas o cadastro em si e trabalho de tela no SAPL:")
        for r in sorted(sem_cadastro, key=lambda x: x["nome"]):
            print(f"      - {r['nome']:<24} {', '.join(r.get('legislaturas', []))}")

    if simular:
        print("\n--simular: nada foi gravado.")
        return 0

    backup = destino.with_suffix(f".json.bak-{datetime.now():%Y%m%d%H%M%S}")
    shutil.copy2(destino, backup)
    destino.write_text(
        json.dumps(catalogo, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nGravado: {destino}")
    print(f"Copia do anterior: {backup.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
