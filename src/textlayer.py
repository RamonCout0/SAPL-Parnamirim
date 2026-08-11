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
        # BUG GRAVE ja corrigido: o filtro comparava substring em QUALQUER
        # lugar da linha, entao uma linha de ementa que so MENCIONA
        # "Parnamirim" - o nome da propria cidade, esperado em enderecos e
        # bairros citados nos pedidos - era jogada fora inteira junto com o
        # timbre. Isso cortou de verdade o final da ementa da indicacao
        # 296/2023 (a frase sobre o bairro "Pirangi do Norte/Parnamirim/RN"
        # sumiu). O guard de tamanho abaixo restringe o filtro a linhas
        # CURTAS e proximas do tamanho do proprio timbre/rodape - uma frase
        # de conteudo real, bem mais longa que a frase de ruido, nunca casa.
        eh_ruido = any(
            ruido.lower() in linha.lower() and len(linha) <= len(ruido) + 20
            for ruido in RUIDO_LINHAS
        )
        if eh_ruido:
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


def extrair_paginas(caminho_pdf: str, mostrar_progresso: bool = False) -> list[Pagina]:
    leitor = PdfReader(caminho_pdf)
    total = len(leitor.pages)
    barra = None
    if mostrar_progresso:
        from .progresso import Progresso
        barra = Progresso(total, prefixo="  lendo paginas ")

    paginas = []
    for i, pg in enumerate(leitor.pages, start=1):
        bruto = pg.extract_text() or ""
        limpo = _limpar(bruto)
        if barra:
            barra.avancar()
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
