"""A sessao do navegador rodando em segundo plano, dirigida pela interface.

Por que uma thread propria: a API sincrona do Playwright precisa ser criada e
usada SEMPRE na mesma thread, e nao pode ser a thread do Tkinter - abrir o
Firefox e navegar leva segundos, e a janela ficaria congelada.

Como as duas conversam:

    interface  --comandos-->  thread   ("continuar", "proxima", "parar")
    interface  <--eventos---  thread   ("login", "preenchida", "fim", ...)

DOIS MODOS
----------
Sem cota (`enviar=0`), a thread preenche uma indicacao e PARA, esperando um
comando. E o modo de sempre: quem confere a tela e salva e a pessoa.

Com cota (`enviar=N`), ela tambem SALVA no SAPL, sem parar, ate somar N
cadastros. Continua parando, e chamando voce, em qualquer um destes casos:

  - a indicacao tem impedimento nos dados (ver sapl.impedimentos): correcao
    sua que ainda nao chegou nela, ja cadastrada antes, sem data, sem autor,
    sem o PDF para anexar;
  - o preenchimento na tela deu falha ou deixou recado de atencao;
  - o SAPL recusou o cadastro, ou nao deu para confirmar que ele aconteceu.

Cada parada dessas devolve a decisao para voce e NAO consome a cota. Clicar em
"Próxima" pula aquela indicacao (sem cadastrar) e o automatico segue nas
seguintes; "Parar" encerra a sessao.
"""
from __future__ import annotations

import queue
import threading
import traceback

from src import sapl
from src.enviados import ler_enviados, registrar_envio
from src.revisao import ler_correcoes


class SessaoSAPL(threading.Thread):
    def __init__(
        self,
        itens: list[dict],
        comandos: queue.Queue,
        eventos: queue.Queue,
        enviar: int = 0,
    ):
        super().__init__(daemon=True)
        self.itens = itens
        self.comandos = comandos
        self.eventos = eventos
        # Quantas indicacoes ainda podem ser CADASTRADAS sozinhas. Conta so
        # cadastro concluido: pular uma indicacao com problema nao gasta cota,
        # senao "enviar 20" entregaria menos de 20 sem ninguem perceber.
        self.cota = max(0, int(enviar or 0))
        self.cota_inicial = self.cota
        self.enviadas: list[str] = []
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

        # Lidos uma vez por sessao: sao a memoria de quem ja foi cadastrada e
        # do que voce corrigiu. O registro de enviados e reescrito a cada
        # cadastro, mas a copia daqui basta - nada mais mexe nele enquanto a
        # sessao roda.
        correcoes = ler_correcoes()
        enviados = ler_enviados()

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
                        # "fim" tambem quando se para aqui: e ele que devolve
                        # os botoes da tela. Sem isto, parar no login deixava a
                        # aba inteira desabilitada ate trocar de aba e voltar.
                        self.eventos.put(("fim", 0, len(self.itens), 0))
                        return
                    pagina.goto(url_form, wait_until="domcontentloaded")

                if sapl.achar(pagina, form["campos"]["ementa"]) is None:
                    rotas = sapl.descobrir_rotas(pagina, base)
                    self.eventos.put(("form_nao_achado", url_form, rotas))
                    return

                total = len(self.itens)
                indice = 0
                while indice < total and not self._parar.is_set():
                    # Cota cumprida: a sessao automatica termina aqui. Seguir
                    # preenchendo a proxima e esperando um clique seria pedir
                    # atencao para uma tela que a pessoa nao pediu para ver.
                    if self.cota_inicial and not self.cota:
                        break

                    item = self.itens[indice]

                    # Antes de qualquer clique: os dados desta indicacao
                    # aguentam ir sozinhos? Conferir aqui, e nao depois de
                    # preencher, evita deixar um formulario meio preenchido na
                    # tela quando a resposta ja era "nao".
                    travas = (sapl.impedimentos(item, correcoes, enviados)
                              if self.cota else [])
                    if travas:
                        self.eventos.put(
                            ("impedida", item, travas, indice + 1, total))
                        if self._esperar_comando() == "parar":
                            break
                        indice += 1
                        continue

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

                    # O automatico so age com a tela limpa: nenhuma falha e
                    # nenhum recado de atencao. Recado aqui nao e detalhe - e
                    # "o autor nao fixou", "o anexo nao foi", coisas que viram
                    # registro oficial errado se ninguem olhar.
                    if self.cota and not falhas and not notas:
                        try:
                            salvou, recado, url = sapl.salvar(pagina, form)
                        except PlaywrightError as e:
                            salvou, recado, url = False, str(e).splitlines()[0], ""
                        if salvou:
                            identificador = f"{item['numero']}/{item['ano']}"
                            # Grava no disco ANTES de qualquer outra coisa: se
                            # o programa morrer no instante seguinte, a materia
                            # ja existe no SAPL e o registro tem de existir
                            # junto, senao a proxima sessao a cadastra de novo.
                            enviados[identificador] = registrar_envio(
                                identificador, url=url)
                            self.enviadas.append(identificador)
                            self.cota -= 1
                            self.eventos.put(
                                ("enviada", item, recado, indice + 1, total,
                                 len(self.enviadas), self.cota))
                            indice += 1
                            continue
                        # Nao salvou: a decisao volta para a pessoa, com o
                        # motivo escrito junto das falhas da tela.
                        falhas = list(falhas) + [f"não cadastrou: {recado}"]

                    self.eventos.put(
                        ("preenchida", item, falhas, notas, indice + 1, total))
                    comando = self._esperar_comando()
                    if comando == "parar":
                        break
                    indice += 1

                self.eventos.put(("fim", indice, total, len(self.enviadas)))
            finally:
                try:
                    nav.close()
                except Exception:
                    pass
