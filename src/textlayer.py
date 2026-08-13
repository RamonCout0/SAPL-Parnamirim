"""Etapa 1: PDF -> texto por pagina -> Markdown.

A maioria dos PDFs de entrada ja vem de um scan com OCR embutido (o lote
original passou pelo OmniPage CSDK 21) - nesse caso so extraimos o texto que
ja esta la. Mas nem todo PDF vem assim: paginas escaneadas sem OCR nenhum
tem texto vazio ou quase vazio. Para essas, ocr.py entra como reserva,
rodando Tesseract localmente so naquela pagina especifica.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import ocr
from .config import RUIDO_LINHAS

# Abaixo disso o texto embutido no PDF e considerado "sem OCR nenhum" - nao
# confundir com paginas de verso legitimas (carimbo "Lido na Sessão"), que
# normalmente tem uns 50-200 caracteres mesmo sendo curtas. Um valor bem baixo
# aqui pega so o caso realmente vazio.
LIMIAR_SEM_OCR = 15


@dataclass
class Pagina:
    numero: int  # 1-based, como no PDF
    texto_bruto: str
    texto: str = ""  # limpo
    linhas: list[str] = field(default_factory=list)
    via_ocr: bool = False  # True se o texto veio do Tesseract, nao do PDF

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
    # Import aqui dentro, nao no topo: a classe Pagina e usada pelas regras de
    # deteccao (detect.py), que assim podem ser importadas e testadas sem
    # exigir as bibliotecas de PDF instaladas.
    from pypdf import PdfReader

    leitor = PdfReader(caminho_pdf)
    total = len(leitor.pages)
    barra = None
    if mostrar_progresso:
        from .progresso import Progresso
        barra = Progresso(total, prefixo="  lendo paginas ")

    paginas = []
    sem_ocr: list[int] = []
    ocr_recuperou = 0
    for i, pg in enumerate(leitor.pages, start=1):
        bruto = pg.extract_text() or ""
        via_ocr = False

        if len(bruto.strip()) < LIMIAR_SEM_OCR:
            sem_ocr.append(i)
            texto_ocr = ocr.ocr_pagina(caminho_pdf, i)
            if len(texto_ocr.strip()) > len(bruto.strip()):
                bruto = texto_ocr
                via_ocr = True
                ocr_recuperou += 1
            # Se o OCR tambem nao achou nada (ou o Tesseract nao esta
            # instalado), a pagina segue com o texto vazio que ja tinha - o
            # resto do pipeline (deteccao de inicio + confianca da ementa)
            # ja manda isso para revisao manual sozinho.

        limpo = _limpar(bruto)
        if barra:
            barra.avancar()
        paginas.append(
            Pagina(
                numero=i,
                texto_bruto=bruto,
                texto=limpo,
                linhas=[l for l in limpo.splitlines() if l.strip()],
                via_ocr=via_ocr,
            )
        )

    if sem_ocr:
        if ocr.disponivel():
            print(
                f"  {len(sem_ocr)} pagina(s) sem OCR embutido - "
                f"Tesseract recuperou texto em {ocr_recuperou}"
            )
        else:
            print(
                f"  AVISO: {len(sem_ocr)} pagina(s) sem OCR embutido e o "
                f"Tesseract nao esta disponivel ({ocr.motivo_indisponivel()}) - "
                "essas paginas vao para revisao manual"
            )

    return paginas


def pagina_para_markdown(p: Pagina) -> str:
    return f"## Página {p.numero}\n\n{p.texto}\n"
