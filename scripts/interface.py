"""Abre a interface grafica.

    .venv\\Scripts\\pythonw scripts\\interface.py

No dia a dia ninguem digita isso: e o que o atalho "SAPL Parnamirim.bat" (e o
.exe da instalacao) chamam por tras. Existe como script para quem esta
desenvolvendo poder abrir a interface direto.

Rodando por pythonw.exe nao existe console: um erro na abertura nao apareceria
em lugar nenhum e a pessoa veria "cliquei e nao aconteceu nada". Por isso todo
erro daqui vira uma janela de aviso E uma linha em output/erro_interface.txt.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

REGISTRO = RAIZ / "output" / "erro_interface.txt"


def _mostrar_erro(titulo: str, mensagem: str, detalhe: str = "") -> None:
    try:
        REGISTRO.parent.mkdir(parents=True, exist_ok=True)
        REGISTRO.write_text(f"{mensagem}\n\n{detalhe}", encoding="utf-8")
    except OSError:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox

        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showerror(
            titulo,
            f"{mensagem}\n\nO detalhe completo foi gravado em:\n{REGISTRO}")
        raiz.destroy()
    except Exception:
        print(f"{titulo}: {mensagem}\n{detalhe}", file=sys.stderr)


def main() -> int:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        # Acontece em algumas instalacoes de Linux, onde o Tk vem separado.
        # No Windows o Python oficial ja traz.
        print(
            "O Tkinter nao esta disponivel neste Python.\n"
            "No Windows, reinstale o Python marcando 'tcl/tk and IDLE'.\n"
            "No Linux: sudo apt install python3-tk",
            file=sys.stderr,
        )
        return 1

    try:
        from gui.app import main as abrir

        return abrir()
    except ImportError as e:
        _mostrar_erro(
            "Falta uma biblioteca",
            f"O programa não conseguiu carregar uma peça necessária: {e}\n\n"
            "O ambiente provavelmente não terminou de ser preparado.",
            traceback.format_exc(),
        )
        return 1
    except Exception as e:  # noqa: BLE001 - ultima barreira antes do silencio
        _mostrar_erro("O programa não abriu", str(e), traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
