"""Caminhos e catalogo de IDs do SAPL."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _raiz() -> Path:
    """A pasta de trabalho: onde ficam input/, output/ e config/.

    Rodando pelo codigo-fonte, e a raiz do repositorio. Rodando pelo .exe, e a
    pasta ONDE O EXE ESTA - nao a de dentro do pacote. A diferenca importa:
    o que esta dentro do .exe e somente leitura e some a cada atualizacao,
    enquanto input/, output/ e as suas correcoes precisam ficar visiveis, do
    lado do programa, para voce abrir e copiar arquivo quando quiser.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _recursos() -> Path:
    """De onde saem os arquivos que VEM junto com o programa (os modelos de
    config). No .exe e a pasta interna do pacote; no codigo-fonte e a propria
    raiz, entao os dois caminhos coincidem e nada e copiado."""
    interno = getattr(sys, "_MEIPASS", None)
    return Path(interno) if interno else _raiz()


RAIZ = _raiz()
RECURSOS = _recursos()
CONFIG_DIR = RAIZ / "config"
OUTPUT_DIR = RAIZ / "output"
INPUT_DIR = RAIZ / "input"

# Arquivos de configuracao que acompanham o programa. Os dois primeiros sao
# tabelas fixas (ids do SAPL, seletores do formulario); os outros dois sao
# trabalho do usuario e por isso sao criados vazios, nunca sobrescritos.
_MODELOS_CONFIG = ["sapl_ids.json", "sapl_form.json", "aliases_aprendidos.json"]

MARKDOWN_DIR = OUTPUT_DIR / "markdown"
PDFS_DIR = OUTPUT_DIR / "pdfs"

# Ollama
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5:3b-instruct"

# Verbos que abrem a ementa. Ordem importa: os mais longos primeiro,
# senao "INDICAR" seria capturado antes de "VEM INDICAR".
#
# INDICO/REITERO/RETIRO (primeira pessoa - "eu indico") existem porque alguns
# vereadores escrevem assim em vez da terceira pessoa "INDICA" ("o vereador
# indica"). Achado num caso real: bloco inteiro caiu em "verbo ilegivel"
# porque so tinhamos a forma de terceira pessoa na lista.
VERBOS_EMENTA = [
    "VEM INDICAR",
    "VENHO INDICAR",
    "VEM REITERAR",
    "VENHO REITERAR",
    "VEM RETIRAR",
    "REITERAR",
    "REITERA",
    "REITERO",
    "RETIRAR",
    "RETIRA",
    "RETIRO",
    "INDICAR",
    "INDICA",
    "INDICO",
]

# Verbos do modelo ANTIGO de indicacao (aparece de 2009 ate meados dos anos
# 2010). Naquele papel a formula nao e "o vereador INDICA", e sim:
#
#   "Apresento a V.Exa., nos termos do Art. 148 do Regimento Interno, a
#    presente Indicacao, SUGERINDO ao Senhor Prefeito <o pedido> por se
#    tratar de medida de interesse publico."
#
# Como "sugerindo" nao estava em lista nenhuma, a ementa saia VAZIA e o
# programa acusava "verbo ilegivel no OCR - transcrever pelo PNG" - um recado
# errado, porque o OCR estava perfeito: quem nao conhecia a palavra era o
# programa. Medido em 26/08/2026 no lote de 2010: 160 das 426 indicacoes
# (38%) caiam assim, todas com o texto limpo e legivel no PDF.
#
# Esta lista e SEPARADA de VERBOS_EMENTA de proposito, e so e consultada
# quando nenhum verbo da lista principal casa. Assim o comportamento dos
# lotes de 2020 em diante - que ja estao conferidos e enviados - nao muda em
# nada: um verbo novo no meio da lista principal poderia casar ANTES do verbo
# certo e reescrever ementa que ja estava boa.
VERBOS_EMENTA_ANTIGOS = [
    # "... a presente Indicacao, SUGERINDO ao Senhor Prefeito <pedido>"
    "SUGERINDO",
    "SUGERE",
    "SUGIRO",
    # "... solicitar a Presidencia da Mesa Diretora, que seja INDICADO ao
    #  Chefe do Executivo Municipal <pedido>". Particípio: "INDICADO" nao casa
    #  em \bINDICA\b (nao ha fronteira de palavra antes do "DO"), entao a
    #  lista principal passava direto por ele.
    "INDICADOS",
    "INDICADAS",
    "INDICADO",
    "INDICADA",
    "SOLICITANDO",
    "SOLICITA",
    "SOLICITO",
]

# Linhas de rodape / cabecalho do papel timbrado que o OCR repete em toda pagina
# e que nao fazem parte do conteudo da indicacao.
RUIDO_LINHAS = [
    "CÂMARA MUNICIPAL DE",
    "PARNAMIRIM",
    "A CASA DO POVO",
    "Câmara Municipal Parnamirim/RN_Johnat Linhares",
    "Castor Vieira Régis",
    "Cohabinal",
    "www.camaradeparnamirim.com.br",
    "Fone: (84)",
]


def preparar_pasta_de_trabalho() -> None:
    """Primeira execucao do .exe: cria as pastas e traz os arquivos de
    configuracao de dentro do pacote para o lado do programa.

    So copia o que NAO existe. Um sapl_ids.json que voce ajustou, ou o
    aliases_aprendidos.json que cresceu com o uso, nunca sao sobrescritos por
    uma atualizacao do programa - seria apagar trabalho seu.
    """
    for d in (INPUT_DIR, OUTPUT_DIR, MARKDOWN_DIR, PDFS_DIR, CONFIG_DIR):
        d.mkdir(parents=True, exist_ok=True)

    if RECURSOS == RAIZ:
        return  # rodando pelo codigo-fonte: origem e destino sao o mesmo lugar

    for nome in _MODELOS_CONFIG:
        destino = CONFIG_DIR / nome
        origem = RECURSOS / "config" / nome
        if not destino.exists() and origem.is_file():
            shutil.copy2(origem, destino)


def carregar_ids() -> dict:
    with open(CONFIG_DIR / "sapl_ids.json", encoding="utf-8") as f:
        return json.load(f)


def garantir_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR, MARKDOWN_DIR, PDFS_DIR):
        d.mkdir(parents=True, exist_ok=True)
