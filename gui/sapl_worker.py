"""A sessao do navegador rodando em segundo plano, dirigida pela interface.

Por que uma thread propria: a API sincrona do Playwright precisa ser criada e
usada SEMPRE na mesma thread, e nao pode ser a thread do Tkinter - abrir o
Firefox e navegar leva segundos, e a janela ficaria congelada.

Como as duas conversam:

    interface  --comandos-->  thread   ("continuar", "proxima", "parar")
    interface  <--eventos---  thread   ("login", "preenchida", "fim", ...)

A thread PARA e espera um comando depois de preencher cada indicacao. E de
proposito: quem confere a tela, anexa o PDF e escreve a data e a pessoa. O
programa nunca salva nada no SAPL sozinho.
"""
from __future__ import annotations

import queue
import threading
import traceback

from src import sapl


class SessaoSAPL(threading.Thread):
    def __init__(self, itens: list[dict], comandos: queue.Queue, eventos: queue.Queue):
        super().__init__(daemon=True)
        self.itens = itens
        self.comandos = comandos
        self.eventos = eventos
        self._parar = threading.Event()

    def parar(self) -> None:
        self._parar.set()
        self.comandos.put("parar")

    # ------------------------------------------------------------------ ciclo
    def run(self) -> None:
        try:
            self._rodar()
        except Exception as e:  # noqa: BLE001 - a interface mostra o texto
            self.eventos.put(("erro", self._explicar(e), traceback.format_exc()))

    def _explicar(self, e: Exception) -> str:
        """Traduz os erros que realmente acontecem em linguagem de gente."""
        texto = str(e)
        if "Executable doesn't exist" in texto or "playwright install" in texto:
            return (
                "O navegador do Playwright ainda não foi instalado nesta "
                "máquina. Abra a aba de instalação (ou rode "
                "'playwright install firefox') e tente de novo."
            )
        if "ERR_CONNECTION" in texto or "NS_ERROR_" in texto or "net::" in texto:
            return ("Não deu para acessar o SAPL. Confira a conexão com a "
                    "internet e se o endereço do sistema está no ar.")
        return f"{type(e).__name__}: {texto}"

    def _esperar_comando(self) -> str:
        """Bloqueia ate a pessoa clicar em alguma coisa na interface."""
        return self.comandos.get()

    def _rodar(self) -> None:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        form = sapl.carregar_form()
        base = form["base_url"].rstrip("/")
        url_form = base + form["caminho_formulario"]

        self.eventos.put(("abrindo",))
        sapl.PERFIL.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            nav = p.firefox.launch_persistent_context(
                user_data_dir=str(sapl.PERFIL),
                headless=False,
                viewport={"width": 1500, "height": 950},
            )
            try:
                pagina = nav.pages[0] if nav.pages else nav.new_page()
                pagina.goto(url_form, wait_until="domcontentloaded")

                if "login" in pagina.url.lower():
                    # O programa nunca digita senha: quem entra e a pessoa, na
                    # janela que abriu. A sessao fica salva no perfil.
                    self.eventos.put(("login", pagina.url))
                    if self._esperar_comando() == "parar":
                        return
                    pagina.goto(url_form, wait_until="domcontentloaded")

                if sapl.achar(pagina, form["campos"]["ementa"]) is None:
                    rotas = sapl.descobrir_rotas(pagina, base)
                    self.eventos.put(("form_nao_achado", url_form, rotas))
                    return

                total = len(self.itens)
                indice = 0
                while indice < total and not self._parar.is_set():
                    item = self.itens[indice]
                    try:
                        pagina = sapl.pagina_valida(nav, pagina)
                        pagina.goto(url_form, wait_until="domcontentloaded")
                        falhas, notas = sapl.preencher(pagina, form, item)
                    except PlaywrightError as e:
                        # Uma indicacao com problema (janela fechada, travou)
                        # nao pode derrubar a sessao inteira: a pessoa decide
                        # se tenta de novo, pula ou para.
                        self.eventos.put(
                            ("erro_indicacao", item, str(e).splitlines()[0],
                             indice + 1, total))
                        comando = self._esperar_comando()
                        if comando == "parar":
                            break
                        if comando == "tentar":
                            continue
                        indice += 1
                        continue

                    self.eventos.put(
                        ("preenchida", item, falhas, notas, indice + 1, total))
                    comando = self._esperar_comando()
                    if comando == "parar":
                        break
                    indice += 1

                self.eventos.put(("fim", indice, total))
            finally:
                try:
                    nav.close()
                except Exception:
                    pass
