"""Blocos que voce mandou juntar - quando a maquina partiu uma indicacao em duas.

A separacao de blocos e feita por dois sinais (o cabecalho com o numero e a
formula juridica de abertura, ver src/detect.py). Os dois falham juntos de vez
em quando: uma folha de anexo que a maquina leu como comeco, um cabecalho que o
OCR destruiu no meio da indicacao. O resultado e sempre o mesmo estrago - a
indicacao vira dois cadastros, cada um com metade das paginas, e o PDF anexado
no SAPL fica incompleto.

Nenhuma regra automatica cobre todos esses casos, entao existe a saida manual:
na tela de conferencia voce olha a imagem, ve que aquele bloco e a continuacao
do anterior, e manda juntar. Fica gravado aqui.

Por que em config/ e nao em output/: e trabalho humano, do mesmo naipe do
correcoes.json. Sobrevive a qualquer rodada do pipeline, pode ser versionado no
git, e uma juncao feita uma vez vale para sempre - inclusive para quem clonar o
repositorio depois.

A chave e (nome do arquivo de origem, pagina em que o bloco comeca). Nao o
numero da indicacao: o numero e justamente o que costuma estar errado nesses
casos, e ele muda quando voce corrige. A pagina nao muda nunca.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import CONFIG_DIR

JUNCOES = CONFIG_DIR / "juncoes.json"

_DOC = (
    "Blocos marcados como continuacao do bloco anterior, por arquivo de "
    "origem. A chave e o nome do PDF de entrada; a lista traz as paginas em "
    "que aquele bloco comecava. Na proxima rodada o pipeline nao abre bloco "
    "nessas paginas - elas passam a fazer parte da indicacao de cima."
)


def ler_juncoes(caminho: Path | None = None) -> dict[str, list[int]]:
    """O que ja foi mandado juntar. Vazio se o arquivo ainda nao existe."""
    caminho = caminho or JUNCOES
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{caminho} esta corrompido ({e}). E o registro das juncoes que "
            "voce fez a mao - conserte o JSON em vez de apagar, senao as "
            "indicacoes voltam a ser partidas em duas."
        ) from e
    juncoes = dados.get("juncoes", {})
    return {arquivo: sorted(set(paginas)) for arquivo, paginas in juncoes.items()}


def _gravar(juncoes: dict[str, list[int]], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps({"_doc": _DOC, "juncoes": {a: sorted(p) for a, p in juncoes.items() if p}},
                   ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )


def juntar(arquivo: str, pagina: int, caminho: Path | None = None) -> None:
    """Marca: o bloco que comeca nesta pagina e continuacao do de cima."""
    caminho = caminho or JUNCOES
    juncoes = ler_juncoes(caminho)
    paginas = set(juncoes.get(arquivo, []))
    paginas.add(int(pagina))
    juncoes[arquivo] = sorted(paginas)
    _gravar(juncoes, caminho)


def separar(arquivo: str, pagina: int, caminho: Path | None = None) -> bool:
    """Desfaz uma juncao. Devolve se havia o que desfazer."""
    caminho = caminho or JUNCOES
    juncoes = ler_juncoes(caminho)
    paginas = set(juncoes.get(arquivo, []))
    if int(pagina) not in paginas:
        return False
    paginas.discard(int(pagina))
    juncoes[arquivo] = sorted(paginas)
    _gravar(juncoes, caminho)
    return True


def aplicar(inicios: list, arquivo: str, caminho: Path | None = None) -> list:
    """Tira da lista os inicios que voce mandou juntar com o anterior.

    Roda logo depois da deteccao e ANTES de deduzir numeros: um bloco que nao
    devia existir nao pode entrar no calculo da sequencia, senao ele desloca a
    deducao dos vizinhos.

    O primeiro inicio do arquivo nunca e removido - nao ha bloco anterior para
    receber as paginas dele, e remove-lo faria as paginas sumirem do lote.
    """
    paginas = set(ler_juncoes(caminho).get(arquivo, []))
    if not paginas:
        return inicios
    return [ini for i, ini in enumerate(inicios)
            if i == 0 or ini.pagina not in paginas]
