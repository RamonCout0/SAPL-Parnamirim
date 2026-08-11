"""Caminhos e catalogo de IDs do SAPL."""
from __future__ import annotations

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_DIR = RAIZ / "config"
OUTPUT_DIR = RAIZ / "output"
INPUT_DIR = RAIZ / "input"

MARKDOWN_DIR = OUTPUT_DIR / "markdown"
PDFS_DIR = OUTPUT_DIR / "pdfs"

# Ollama
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5:3b-instruct"

# Verbos que abrem a ementa. Ordem importa: os mais longos primeiro,
# senao "INDICAR" seria capturado antes de "VEM INDICAR".
VERBOS_EMENTA = [
    "VEM INDICAR",
    "VENHO INDICAR",
    "VEM REITERAR",
    "VENHO REITERAR",
    "VEM RETIRAR",
    "REITERAR",
    "REITERA",
    "RETIRAR",
    "RETIRA",
    "INDICAR",
    "INDICA",
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


def carregar_ids() -> dict:
    with open(CONFIG_DIR / "sapl_ids.json", encoding="utf-8") as f:
        return json.load(f)


def garantir_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR, MARKDOWN_DIR, PDFS_DIR):
        d.mkdir(parents=True, exist_ok=True)
