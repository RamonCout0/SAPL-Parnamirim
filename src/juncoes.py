"""Onde cada indicacao comeca, quando a maquina erra a fronteira.

A separacao de blocos e feita por dois sinais (o cabecalho com o numero e a
formula juridica de abertura, ver src/detect.py). Os dois erram, e erram nos
DOIS sentidos - por isso este arquivo guarda duas marcacoes opostas:

  JUNCAO (juntar) - a maquina abriu bloco onde nao comecava indicacao nova:
                    uma folha de anexo lida como comeco, um verso solto. A
                    indicacao vira dois cadastros, cada um com metade das
                    paginas, e o PDF anexado no SAPL fica incompleto.

  CORTE (cortar)  - o contrario, e o mais perigoso dos dois: a maquina NAO
                    abriu bloco onde a indicacao seguinte comecava. Caso real,
                    a 610 com a 609: o cabecalho da 609 saiu ilegivel, as
                    paginas das duas viraram um bloco so, e o estrago e duplo
                    - o PDF da 610 leva dentro um documento que nao e dela, e
                    a 609 DESAPARECE do lote. Ninguem ve que ela sumiu, porque
                    ela nao chega a existir em lugar nenhum para dar erro.

Nenhuma regra automatica cobre todos esses casos, entao existe a saida manual:
na tela de conferencia voce olha a imagem e diz onde a fronteira esta errada.
Fica gravado aqui.

Por que em config/ e nao em output/: e trabalho humano, do mesmo naipe do
correcoes.json. Sobrevive a qualquer rodada do pipeline, pode ser versionado no
git, e uma marcacao feita uma vez vale para sempre - inclusive para quem clonar
o repositorio depois.

A chave e sempre (nome do arquivo de origem, pagina). Nao o numero da
indicacao: o numero e justamente o que costuma estar errado nesses casos, e ele
muda quando voce corrige. A pagina nao muda nunca.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import CONFIG_DIR
from .detect import Inicio

JUNCOES = CONFIG_DIR / "juncoes.json"

_DOC = (
    "Fronteiras de bloco corrigidas a mao, por arquivo de origem. A chave e o "
    "nome do PDF de entrada. Em 'juncoes', as paginas que NAO abrem indicacao "
    "nova - elas passam a fazer parte da indicacao de cima. Em 'cortes', o "
    "contrario: paginas que ABREM indicacao mesmo sem a maquina ter visto "
    "cabecalho nenhum, cada uma com o numero que voce leu no papel. Vale a "
    "partir da proxima rodada do pipeline."
)


def _ler(caminho: Path) -> dict:
    """O arquivo cru. Vazio se ainda nao existe; erro se existe e esta quebrado.

    Devolver vazio num JSON corrompido desfaria EM SILENCIO tudo que ja foi
    marcado - as fronteiras erradas voltariam todas e ninguem saberia por que.
    """
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{caminho} esta corrompido ({e}). E o registro das juncoes e dos "
            "cortes que voce fez a mao - conserte o JSON em vez de apagar, "
            "senao as indicacoes voltam a ser partidas (e grudadas) como antes."
        ) from e


def ler_juncoes(caminho: Path | None = None) -> dict[str, list[int]]:
    """O que ja foi mandado juntar. Vazio se o arquivo ainda nao existe."""
    juncoes = _ler(caminho or JUNCOES).get("juncoes", {})
    return {arquivo: sorted(set(paginas)) for arquivo, paginas in juncoes.items()}


def ler_cortes(caminho: Path | None = None) -> dict[str, list[dict]]:
    """Onde voce mandou abrir bloco, por arquivo: [{"pagina": n, "numero": n}].

    Sai ordenado por pagina porque e assim que os cortes entram na lista de
    inicios, e a lista de inicios tem de estar em ordem - ver `aplicar`.
    """
    cortes = _ler(caminho or JUNCOES).get("cortes", {})
    return {
        arquivo: sorted(
            ({"pagina": int(c["pagina"]), "numero": int(c["numero"])} for c in lista),
            key=lambda c: c["pagina"],
        )
        for arquivo, lista in cortes.items()
    }


def _gravar(juncoes: dict[str, list[int]], cortes: dict[str, list[dict]],
            caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(
            {
                "_doc": _DOC,
                "juncoes": {a: sorted(p) for a, p in juncoes.items() if p},
                "cortes": {a: sorted(c, key=lambda x: x["pagina"])
                           for a, c in cortes.items() if c},
            },
            ensure_ascii=False, indent=1, sort_keys=True,
        ),
        encoding="utf-8",
    )


def juntar(arquivo: str, pagina: int, caminho: Path | None = None) -> None:
    """Marca: o bloco que comeca nesta pagina e continuacao do de cima."""
    caminho = caminho or JUNCOES
    juncoes = ler_juncoes(caminho)
    cortes = ler_cortes(caminho)
    paginas = set(juncoes.get(arquivo, []))
    paginas.add(int(pagina))
    juncoes[arquivo] = sorted(paginas)
    # Juntar e cortar sao ordens opostas sobre a MESMA pagina: guardar as duas
    # deixaria o pipeline desempatando sozinho, e a ultima palavra tem de ser a
    # sua. A marcacao mais recente apaga a anterior.
    cortes[arquivo] = [c for c in cortes.get(arquivo, []) if c["pagina"] != int(pagina)]
    _gravar(juncoes, cortes, caminho)


def separar(arquivo: str, pagina: int, caminho: Path | None = None) -> bool:
    """Desfaz uma juncao. Devolve se havia o que desfazer."""
    caminho = caminho or JUNCOES
    juncoes = ler_juncoes(caminho)
    paginas = set(juncoes.get(arquivo, []))
    if int(pagina) not in paginas:
        return False
    paginas.discard(int(pagina))
    juncoes[arquivo] = sorted(paginas)
    _gravar(juncoes, ler_cortes(caminho), caminho)
    return True


def cortar(arquivo: str, pagina: int, numero: int,
           caminho: Path | None = None) -> None:
    """Marca: nesta pagina comeca a indicacao `numero`, mesmo sem cabecalho.

    O numero e obrigatorio de proposito. Um inicio sem numero depende da
    deducao pela sequencia, e quando a deducao nao fecha o bloco e DESCARTADO
    (ver detect.montar_blocos): as paginas sumiriam do lote justamente na
    operacao que voce fez para nao perde-las. Aqui nao ha o que deduzir - voce
    esta com a pagina na tela e o numero escrito nela.
    """
    caminho = caminho or JUNCOES
    juncoes = ler_juncoes(caminho)
    cortes = ler_cortes(caminho)
    lista = [c for c in cortes.get(arquivo, []) if c["pagina"] != int(pagina)]
    lista.append({"pagina": int(pagina), "numero": int(numero)})
    cortes[arquivo] = sorted(lista, key=lambda c: c["pagina"])
    # Ver juntar(): as duas ordens nao convivem na mesma pagina.
    juncoes[arquivo] = [p for p in juncoes.get(arquivo, []) if p != int(pagina)]
    _gravar(juncoes, cortes, caminho)


def desfazer_corte(arquivo: str, pagina: int, caminho: Path | None = None) -> bool:
    """Desfaz um corte. Devolve se havia o que desfazer."""
    caminho = caminho or JUNCOES
    cortes = ler_cortes(caminho)
    lista = cortes.get(arquivo, [])
    restante = [c for c in lista if c["pagina"] != int(pagina)]
    if len(restante) == len(lista):
        return False
    cortes[arquivo] = restante
    _gravar(ler_juncoes(caminho), cortes, caminho)
    return True


def aplicar(inicios: list, arquivo: str, caminho: Path | None = None) -> list:
    """Aplica as duas marcacoes sobre os inicios que a maquina achou.

    Roda logo depois da deteccao e ANTES de deduzir numeros: um bloco que nao
    devia existir nao pode entrar no calculo da sequencia (ele desloca a
    deducao dos vizinhos), e um bloco que devia existir precisa estar la para
    ocupar o lugar dele.

    O primeiro inicio do arquivo nunca e removido - nao ha bloco anterior para
    receber as paginas dele, e remove-lo faria as paginas sumirem do lote.

    A lista volta ordenada por pagina. Nao e detalhe de arrumacao: montar_blocos
    fecha cada bloco na pagina anterior a do PROXIMO da lista, entao um corte
    inserido fora de ordem daria a um bloco um fim antes do proprio comeco.
    """
    caminho = caminho or JUNCOES
    juntadas = set(ler_juncoes(caminho).get(arquivo, []))
    cortes = ler_cortes(caminho).get(arquivo, [])
    if not juntadas and not cortes:
        return inicios

    restantes = [ini for i, ini in enumerate(inicios)
                 if i == 0 or ini.pagina not in juntadas]
    if not cortes:
        return restantes

    # Um corte numa pagina que a maquina JA reconheceu como inicio nao tem o
    # que fazer: a fronteira ali ja esta certa. Inserir assim mesmo criaria
    # dois blocos comecando na mesma pagina, um deles sem pagina nenhuma.
    ja_sao_inicio = {ini.pagina for ini in restantes}
    for c in cortes:
        if c["pagina"] in ja_sao_inicio:
            continue
        restantes.append(
            Inicio(
                pagina=c["pagina"],
                numero=c["numero"],
                ano=None,            # o ano do lote manda - ver montar_blocos
                tem_cabecalho=False,
                tem_estrutura=False,
                corte_manual=True,
            )
        )
    return sorted(restantes, key=lambda ini: ini.pagina)
