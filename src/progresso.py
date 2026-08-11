"""Barra de progresso no terminal - so biblioteca padrao, sem dependencia nova.

Usa "\r" para reescrever a mesma linha. Funciona no cmd, PowerShell e
terminais Unix. Cada Progresso guarda o maior tamanho de linha ja escrito
para apagar o resto de uma linha anterior mais longa (senao sobra lixo).
"""
from __future__ import annotations

import sys
import time


class Progresso:
    def __init__(self, total: int, prefixo: str = "", largura: int = 28):
        self.total = max(total, 1)
        self.prefixo = prefixo
        self.largura = largura
        self.atual = 0
        self._inicio = time.monotonic()
        self._maior_linha = 0

    def avancar(self, passo: int = 1) -> None:
        self.atual = min(self.atual + passo, self.total)
        self._desenhar()

    def encerrar(self) -> None:
        """Garante a linha em 100% mesmo se o total nao bateu exato."""
        self.atual = self.total
        self._desenhar()

    def _desenhar(self) -> None:
        fracao = self.atual / self.total
        preenchido = int(self.largura * fracao)
        barra = "#" * preenchido + "-" * (self.largura - preenchido)
        decorrido = time.monotonic() - self._inicio

        if 0 < self.atual < self.total:
            restante = decorrido / self.atual * (self.total - self.atual)
            tempo = f" ~{_formatar(restante)} restantes"
        elif self.atual >= self.total:
            tempo = f" em {_formatar(decorrido)}"
        else:
            tempo = ""

        linha = f"\r{self.prefixo}[{barra}] {self.atual}/{self.total} ({fracao*100:5.1f}%){tempo}"
        self._maior_linha = max(self._maior_linha, len(linha))
        sys.stdout.write(linha.ljust(self._maior_linha))
        sys.stdout.flush()
        if self.atual >= self.total:
            sys.stdout.write("\n")


def _formatar(segundos: float) -> str:
    segundos = max(int(segundos), 0)
    if segundos < 60:
        return f"{segundos}s"
    minutos, resto = divmod(segundos, 60)
    return f"{minutos}min{resto:02d}s"
