"""Etapa 1: PDF -> texto por pagina -> Markdown.

O PDF de entrada e um scan produzido pelo OmniPage CSDK 21, que ja embutiu
uma camada de texto OCR. Nao precisamos de Tesseract: basta extrair essa
camada e limpar o ruido do papel timbrado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pypdf import PdfReader

from .config import RUIDO_LINHAS


@dataclass
class Pagina:
    numero: int  # 1-based, como no PDF
    texto_bruto: str
    texto: str = ""  # limpo
    linhas: list[str] = field(default_factory=list)

    @property
    def densidade(self) -> int:
        """Quantidade de texto util. Paginas de verso ficam abaixo de ~300."""
        return len(self.texto)


def _limpar(texto: str) -> str:
    """Remove rodape/timbre e normaliza espacos, preservando paragrafos."""
    saida = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            saida.append("")
            continue
        if any(ruido.lower() in linha.lower() for ruido in RUIDO_LINHAS):
            continue
        # Linhas que sao so sujeira de OCR (rabiscos, assinatura digital):
        # menos de 40% de caracteres alfanumericos.
        alnum = sum(c.isalnum() or c.isspace() for c in linha)
        if len(linha) > 3 and alnum / len(linha) < 0.4:
            continue
        saida.append(re.sub(r"[ \t]+", " ", linha))

    texto = "\n".join(saida)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def extrair_paginas(caminho_pdf: str) -> list[Pagina]:
    leitor = PdfReader(caminho_pdf)
    paginas = []
    for i, pg in enumerate(leitor.pages, start=1):
        bruto = pg.extract_text() or ""
        limpo = _limpar(bruto)
        paginas.append(
            Pagina(
                numero=i,
                texto_bruto=bruto,
                texto=limpo,
                linhas=[l for l in limpo.splitlines() if l.strip()],
            )
        )
    return paginas


def pagina_para_markdown(p: Pagina) -> str:
    return f"## Página {p.numero}\n\n{p.texto}\n"
