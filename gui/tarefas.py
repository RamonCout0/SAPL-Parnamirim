"""Rodar o pipeline sem congelar a janela.

O Tkinter e de uma thread so: qualquer coisa demorada feita na thread da
interface trava a janela inteira (o Windows pinta "Nao está respondendo").
O pipeline le PDF, roda OCR e escreve arquivos - facilmente minutos.

Entao: a tarefa roda numa thread separada e conversa com a interface por uma
fila. A thread NUNCA toca um widget; ela so poe eventos na fila, e a interface
os consome no seu proprio tempo com `after()`. Essa e a unica forma segura -
mexer em widget de fora da thread principal do Tk trava ou quebra de um jeito
dificil de reproduzir.

De quebra, isto captura o que o pipeline imprime (ele foi escrito para
terminal, com print e barra de progresso em "\\r") e transforma em linhas de
log e porcentagem para a barra da tela.
"""
from __future__ import annotations

import io
import queue
import re
import threading
import traceback
from typing import Any, Callable

# A barra do terminal: "  lendo paginas [####----] 3/8 ( 37.5%) ~2s restantes"
_BARRA_RE = re.compile(r"^(.*?)\[[#\-]+\]\s+(\d+)/(\d+)")


class _SaidaParaFila(io.TextIOBase):
    """Faz as vezes de sys.stdout enquanto a tarefa roda.

    Junta os pedacos ate fechar uma linha. "\\r" (a barra de progresso, que
    reescreve a mesma linha do terminal) vira evento de progresso em vez de
    linha nova de log - senao o log teria centenas de linhas quase iguais.
    """

    def __init__(self, fila: queue.Queue):
        self.fila = fila
        self._buffer = ""

    def write(self, texto: str) -> int:
        self._buffer += texto
        while True:
            corte = min(
                (i for i in (self._buffer.find("\n"), self._buffer.find("\r")) if i >= 0),
                default=-1,
            )
            if corte < 0:
                break
            pedaco, marca = self._buffer[:corte], self._buffer[corte]
            self._buffer = self._buffer[corte + 1:]
            self._publicar(pedaco, transitorio=(marca == "\r"))
        return len(texto)

    def flush(self) -> None:
        # O pipeline chama flush() com a barra ainda no buffer (sem \r no
        # fim). Sem isto, a barra so apareceria quando a linha fechasse.
        if self._buffer.strip():
            self._publicar(self._buffer, transitorio=True)

    def _publicar(self, linha: str, transitorio: bool) -> None:
        limpa = linha.rstrip()
        if not limpa.strip():
            return
        m = _BARRA_RE.match(limpa)
        if m:
            rotulo, atual, total = m.group(1).strip(), int(m.group(2)), int(m.group(3))
            self.fila.put(("progresso", rotulo, atual, total))
            return
        self.fila.put(("transitorio" if transitorio else "linha", limpa))


class Tarefa:
    """Uma funcao demorada rodando em segundo plano.

    Eventos postos na fila:
        ("linha", texto)                 saida do pipeline, para o log
        ("transitorio", texto)           status momentaneo (sobrescreve)
        ("progresso", rotulo, i, total)  para a barra
        ("fim", resultado)               terminou bem
        ("erro", mensagem, detalhe)      levantou excecao
    """

    def __init__(self, alvo: Callable[[], Any], fila: queue.Queue):
        self.alvo = alvo
        self.fila = fila
        self._thread: threading.Thread | None = None

    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self._rodar, daemon=True)
        self._thread.start()

    def rodando(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _rodar(self) -> None:
        import contextlib
        import sys

        saida = _SaidaParaFila(self.fila)
        try:
            # stderr junto: um aviso de biblioteca no meio do processamento
            # tem de aparecer no log, nao sumir num terminal que nem existe
            # quando a interface roda pelo .exe.
            with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
                resultado = self.alvo()
            saida.flush()
            self.fila.put(("fim", resultado))
        except Exception as e:  # noqa: BLE001 - a interface mostra o texto
            detalhe = traceback.format_exc()
            # O erro tem de chegar na tela: sem terminal, uma excecao engolida
            # aqui deixaria a interface parada para sempre, sem explicacao.
            self.fila.put(("erro", f"{type(e).__name__}: {e}", detalhe))
        finally:
            try:
                sys.stdout.flush()
            except Exception:
                pass


def escoar(fila: queue.Queue, limite: int = 200) -> list[tuple]:
    """Tira os eventos acumulados sem bloquear.

    O limite existe para o desenho da tela nunca ficar refem da velocidade da
    tarefa: numa rodada grande chegam milhares de eventos, e processar todos
    de uma vez travaria a janela pelo motivo oposto ao que a thread resolveu.
    """
    eventos = []
    for _ in range(limite):
        try:
            eventos.append(fila.get_nowait())
        except queue.Empty:
            break
    return eventos
