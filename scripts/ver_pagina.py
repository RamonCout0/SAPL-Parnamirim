"""Inspeciona paginas especificas: texto cru do OCR e texto limpo lado a lado.

Ferramenta de depuracao para quando o diagnostico acusar um bloco torto.

    python scripts\\ver_pagina.py "caminho\\do.pdf" 7 8 9
    python scripts\\ver_pagina.py "caminho\\do.pdf" 7-13
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pypdf import PdfReader

from src.textlayer import _limpar


def expandir(args: list[str]) -> list[int]:
    nums: list[int] = []
    for a in args:
        if "-" in a:
            ini, fim = a.split("-")
            nums.extend(range(int(ini), int(fim) + 1))
        else:
            nums.append(int(a))
    return nums


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    leitor = PdfReader(sys.argv[1])
    limite = int(__import__("os").environ.get("VER_LIMITE", "700"))

    for n in expandir(sys.argv[2:]):
        bruto = leitor.pages[n - 1].extract_text() or ""
        limpo = _limpar(bruto)
        print(f"\n{'='*74}\nPAGINA {n}  (cru {len(bruto)} ch / limpo {len(limpo)} ch)\n{'='*74}")
        print("--- CRU ---")
        print(bruto[:limite])
        print("--- LIMPO ---")
        print(limpo[:limite])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
