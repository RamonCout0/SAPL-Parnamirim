"""Confere e prepara o que o programa precisa para funcionar.

O usuario final nao abre terminal, nao cria .venv e nao roda "pip install".
Ele descompacta uma pasta e clica no programa. Tudo que faltar tem de ser
descoberto e resolvido aqui dentro, com aviso na tela.

Tres coisas nao cabem no pacote e sao resolvidas na primeira execucao:

  navegador (Playwright/Firefox)  ~90 MB, baixado na hora - so e preciso na
                                  etapa de enviar ao SAPL
  Tesseract                       OPCIONAL: OCR de reserva para pagina
                                  escaneada sem camada de texto nenhuma
  Ollama                          OPCIONAL: sugestoes para leitura dificil;
                                  nunca decide nada que va para o SAPL

So o navegador e obrigatorio, e mesmo assim so para a terceira aba. As duas
primeiras (processar e conferir) funcionam sem nada disso.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Peca:
    nome: str
    ok: bool
    obrigatoria: bool
    detalhe: str
    como_resolver: str = ""

    @property
    def situacao(self) -> str:
        if self.ok:
            return "ok"
        return "falta" if self.obrigatoria else "opcional"


def _sem_janela() -> dict:
    """Impede o piscar de janela preta do console ao chamar um programa
    externo - a interface roda sem console nenhum."""
    if sys.platform != "win32":
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": info, "creationflags": subprocess.CREATE_NO_WINDOW}


# --------------------------------------------------------------- navegador
def _driver_do_playwright() -> tuple[str, str] | None:
    """O node + cli.js que o proprio pacote do Playwright traz.

    Chamamos esse par diretamente em vez de "python -m playwright install":
    dentro do .exe nao existe python.exe para invocar.
    """
    try:
        from playwright._impl._driver import compute_driver_executable

        caminho = compute_driver_executable()
        if isinstance(caminho, (tuple, list)):
            return str(caminho[0]), str(caminho[1])
        return str(caminho), ""
    except Exception:
        return None


def _pasta_dos_navegadores() -> Path:
    """Onde o Playwright guarda os navegadores baixados."""
    escolhida = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if escolhida:
        return Path(escolhida)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def navegador_instalado() -> bool:
    """Confere olhando a pasta, sem subir o Playwright.

    Abrir o Playwright so para perguntar "voce esta instalado?" custa alguns
    segundos e, quando o navegador NAO esta la, ainda despeja aviso de asyncio
    na saida - que a interface captura e mostra no log, assustando quem le.
    Procurar o arquivo e instantaneo e silencioso.
    """
    pasta = _pasta_dos_navegadores()
    if not pasta.is_dir():
        return False  # nunca foi baixado nada: nao ha o que investigar
    if any(pasta.glob("firefox-*/firefox/firefox*")):
        return True

    # Instalacao fora do padrao (outra versao do Playwright pode mudar o
    # arranjo das pastas): confirma pela biblioteca, em silencio, para nao
    # dizer "falta" para quem ja tem.
    import contextlib
    import io as _io

    try:
        from playwright.sync_api import sync_playwright

        with contextlib.redirect_stderr(_io.StringIO()):
            with sync_playwright() as p:
                return Path(p.firefox.executable_path).exists()
    except Exception:
        return False


def instalar_navegador(ao_sair_linha=None) -> bool:
    """Baixa o Firefox do Playwright. Devolve True se deu certo.

    ao_sair_linha recebe cada linha do download, para a tela mostrar o
    andamento em vez de ficar parada por dois minutos.
    """
    driver = _driver_do_playwright()
    if driver is None:
        if ao_sair_linha:
            ao_sair_linha("Nao encontrei o instalador que vem com o programa.")
        return False

    node, cli = driver
    comando = [node, cli, "install", "firefox"] if cli else [node, "install", "firefox"]

    try:
        from playwright._impl._driver import get_driver_env

        ambiente = get_driver_env()
    except Exception:
        ambiente = dict(os.environ)

    try:
        processo = subprocess.Popen(
            comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=ambiente,
            **_sem_janela(),
        )
    except OSError as e:
        if ao_sair_linha:
            ao_sair_linha(f"Nao deu para iniciar o download: {e}")
        return False

    ultimo_percentual = -100
    for bruta in processo.stdout or []:
        linha = _limpar_saida(bruta)
        if not linha or not ao_sair_linha:
            continue
        percentual = _percentual(linha)
        if percentual is None:
            ao_sair_linha(linha)
        elif percentual - ultimo_percentual >= 10 or percentual == 100:
            # A barra do Playwright reescreve a mesma linha dezenas de vezes
            # por segundo. No log da tela isso viraria centenas de linhas
            # quase iguais: de 10 em 10 por cento ja diz o que interessa.
            ultimo_percentual = percentual
            ao_sair_linha(f"baixando ... {percentual}%")
    return processo.wait() == 0


# Codigos de cor do terminal ("\x1b[2m"). Numa caixa de texto eles apareceriam
# como lixo no meio da frase.
_CORES_RE = re.compile(r"\x1b\[[0-9;]*m|\[\d{1,2}m")
_PERCENTUAL_RE = re.compile(r"(\d{1,3})%")


def _limpar_saida(linha: str) -> str:
    return _CORES_RE.sub("", linha).strip(" |\r\n")


def _percentual(linha: str) -> int | None:
    m = _PERCENTUAL_RE.search(linha)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- conferir
def conferir() -> list[Peca]:
    """O estado de cada peca, para a tela mostrar de uma vez."""
    pecas = []

    tem_navegador = navegador_instalado()
    pecas.append(Peca(
        nome="Navegador (Firefox do Playwright)",
        ok=tem_navegador,
        obrigatoria=True,
        detalhe=("instalado" if tem_navegador else
                 "ainda nao baixado - cerca de 90 MB, precisa de internet"),
        como_resolver="" if tem_navegador else
        "Necessário só para a aba 3 (enviar ao SAPL). Clique em Preparar.",
    ))

    from . import ocr

    tem_tesseract = ocr.disponivel()
    pecas.append(Peca(
        nome="Tesseract (OCR de reserva)",
        ok=tem_tesseract,
        obrigatoria=False,
        detalhe=("instalado" if tem_tesseract else ocr.motivo_indisponivel()
                 or "nao encontrado"),
        como_resolver="" if tem_tesseract else
        "Sem ele, página escaneada sem camada de texto vai direto para a aba "
        "de conferência, em vez de ser lida automaticamente. O resto funciona "
        "normalmente.",
    ))

    from . import ollama_client

    tem_ollama = ollama_client.esta_no_ar()
    pecas.append(Peca(
        nome="Ollama (sugestões de leitura)",
        ok=tem_ollama,
        obrigatoria=False,
        detalhe="respondendo" if tem_ollama else "não está rodando",
        como_resolver="" if tem_ollama else
        "Opcional. Só sugere leituras difíceis para você conferir — nunca "
        "decide nada que vá para o SAPL.",
    ))

    return pecas


def tudo_pronto(pecas: list[Peca] | None = None) -> bool:
    pecas = pecas if pecas is not None else conferir()
    return all(p.ok for p in pecas if p.obrigatoria)
