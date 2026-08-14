"""OCR de reserva com Tesseract - so para paginas que vieram do scanner SEM
nenhuma camada de texto (nao passaram pelo OmniPage, ou o OCR original
falhou naquela pagina especifica).

So entra em acao quando o texto embutido no PDF esta vazio/quase vazio. A
maioria das paginas ja vem com OCR e nunca passa por aqui - o custo extra
(Tesseract e bem mais lento que so ler o texto que ja esta no PDF) so incide
onde e realmente preciso.

Se o Tesseract nao estiver instalado, este modulo NAO quebra o pipeline: so
devolve texto vazio, a pagina segue sem texto e o resto do pipeline (que ja
foi desenhado para "tolerancia zero") manda ela para revisao manual sozinho -
exatamente como se ninguem tivesse tentado o OCR.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import RAIZ

IDIOMA = "por"
ESCALA_RENDER = 3.0  # ~216 dpi - equilibrio entre nitidez e velocidade

# Pacote de portugues baixado por scripts\instalar.ps1 (ou manualmente) para
# dentro do proprio projeto - nao depende de conseguir escrever em
# "C:\Program Files\Tesseract-OCR\tessdata", que normalmente exige admin.
TESSDATA_DIR = RAIZ / "tessdata"

# Onde o instalador do Windows costuma colocar o tesseract.exe quando o PATH
# ainda nao foi atualizado na sessao atual (comum logo depois de instalar).
_CAMINHOS_COMUNS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

_disponivel: bool | None = None
_motivo_indisponivel = ""


def _achar_executavel() -> str | None:
    achado = shutil.which("tesseract")
    if achado:
        return achado
    for caminho in _CAMINHOS_COMUNS:
        if Path(caminho).is_file():
            return caminho
    return None


def disponivel() -> bool:
    """Confere uma vez so (cache) se o Tesseract + pacote de portugues estao
    prontos para uso."""
    global _disponivel, _motivo_indisponivel
    if _disponivel is None:
        try:
            import pytesseract

            exe = _achar_executavel()
            if not exe:
                raise RuntimeError(
                    "tesseract.exe nao encontrado (nem no PATH, nem nos "
                    "caminhos comuns de instalacao)"
                )
            pytesseract.pytesseract.tesseract_cmd = exe

            if not (TESSDATA_DIR / f"{IDIOMA}.traineddata").is_file():
                raise RuntimeError(
                    f"{TESSDATA_DIR / (IDIOMA + '.traineddata')} nao existe - "
                    "baixe o pacote de portugues (ver README)"
                )
            # Variavel de ambiente, nao "--tessdata-dir" na config string: o
            # pytesseract passa a config para o processo sem envolver um
            # shell, entao aspas em volta do caminho iam parar dentro do
            # argumento literalmente (o Tesseract tentava abrir um arquivo
            # com aspas no nome e falhava).
            os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)

            pytesseract.get_tesseract_version()
            _disponivel = True
        except Exception as e:
            _disponivel = False
            _motivo_indisponivel = str(e)
    return _disponivel


def motivo_indisponivel() -> str:
    return _motivo_indisponivel


def ocr_pagina(caminho_pdf: str, numero_pagina: int) -> str:
    """OCR de uma pagina (1-based). Devolve "" se o Tesseract nao estiver
    disponivel ou a extracao falhar - nunca lanca excecao, para uma pagina
    problematica nao derrubar o pipeline inteiro."""
    if not disponivel():
        return ""
    try:
        import pypdfium2 as pdfium
        import pytesseract

        doc = pdfium.PdfDocument(caminho_pdf)
        try:
            pagina = doc[numero_pagina - 1]
            imagem = pagina.render(scale=ESCALA_RENDER).to_pil()
        finally:
            doc.close()
        return pytesseract.image_to_string(imagem, lang=IDIOMA)
    except Exception:
        return ""
