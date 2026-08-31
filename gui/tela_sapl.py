"""Tela 3: mandar as indicacoes prontas para o SAPL.

Dois botoes, duas maneiras de trabalhar:

  "Abrir o SAPL e preencher" - o programa preenche e PARA em cada indicacao.
  Voce confere a tela, clica em salvar no SAPL e depois em "Próxima" aqui. E o
  caminho de sempre, bom para as primeiras vezes e para conferir por amostra.

  "Enviar automático" - voce diz QUANTAS e o programa preenche e salva sozinho,
  uma atras da outra, ate somar essa quantidade. Para tudo, digite o total.

O automatico nao e o manual sem conferencia: e o manual com a conferencia
feita antes, nos dados. Cada indicacao passa por sapl.impedimentos() e so vai
sozinha se nao sobrar nenhuma objecao - inclusive a de que a correcao que voce
digitou na aba 2 ja chegou ate ela. Qualquer duvida para a fila e chama voce.
"""
from __future__ import annotations

import json
import queue
import tkinter as tk
from tkinter import messagebox, ttk

from src.config import OUTPUT_DIR
from src.enviados import (AUTOMATICO, DECLARADO, esquecer, ler_enviados,
                          marcar_varias)
from src.revisao import CORRECOES
from src.sapl import caminho_do_pdf, cortar_do_numero, entre_numeros

from . import visual
from .sapl_worker import SessaoSAPL
from .tarefas import escoar


class TelaSAPL(ttk.Frame):
    def __init__(self, pai, app):
        super().__init__(pai, padding=visual.px(16))
        self.app = app
        self.prontas: list[dict] = []
        self.enviadas: dict[str, dict] = {}
        self.total_cota = 0
        self.eventos: queue.Queue = queue.Queue()
        self.comandos: queue.Queue = queue.Queue()
        self.sessao: SessaoSAPL | None = None
        self.item_atual: dict | None = None
        # O que a ultima marcacao "ja enviei ate aqui" tirou da fila -
        # e o que o botao Desfazer devolve.
        self._ultimas_marcadas: list[str] = []

        self._montar()
        self.recarregar()

    # --------------------------------------------------------------- layout
    def _montar(self) -> None:
        p = visual.px

        # Mesma area rolavel das abas 1 e 4. Aqui ela resolve um caso especifico:
        # quando a sessao abre, o painel da indicacao entra embaixo e, numa
        # janela de 560 de altura, nao havia espaco para ele - os botoes
        # "Próxima" e "Parar" ficavam com 1 pixel de altura, presentes e
        # inclicaveis. Rolando, eles existem sempre.
        area, self.corpo = visual.area_rolavel(self)
        area.pack(fill="both", expand=True)

        topo = ttk.Frame(self.corpo)
        topo.pack(fill="x")
        self.titulo = ttk.Label(topo, text="Indicações prontas", style="Titulo.TLabel")
        self.titulo.pack(side="left")
        # Placar na MESMA linha do titulo: numa janela de 560 de altura, cada
        # linha a mais aqui em cima e uma linha a menos na tabela.
        self._montar_placar(topo)

        # Aviso de dados velhos: mora acima de tudo porque, quando aparece,
        # nada mais nesta tela deve ser usado antes de resolve-lo.
        self.caixa_velha = visual.aviso(self.corpo, "", "erro")

        self._montar_fila()
        self._montar_ja_enviadas()
        self._montar_automatico()

        # O painel vai para BAIXO antes de a tabela ser criada. Assim, quando
        # ele aparece no meio de uma sessao, quem cede espaco e a tabela (que
        # estica) e nao os botoes - que numa janela baixa saiam da tela.
        self._montar_painel()

        self.moldura = moldura = ttk.Frame(self.corpo)
        moldura.pack(fill="both", expand=True, pady=(p(12), 0))
        colunas = ("numero", "data", "autor", "ementa", "situacao")
        self.tabela = ttk.Treeview(moldura, columns=colunas, show="headings",
                                   height=6)
        titulos = {"numero": "Indicação", "data": "Apresentada em",
                   "autor": "Autor", "ementa": "Ementa", "situacao": "Situação"}
        # peso: quanto cada coluna cresce quando a janela alarga. A ementa leva
        # quase tudo porque e o unico texto que se beneficia de espaco.
        self.pesos = {"numero": 0, "data": 0, "autor": 2, "ementa": 6, "situacao": 2}
        # A largura minima sai do TEXTO DO CABECALHO, medido na fonte que vai
        # de fato desenha-lo. Numeros escritos na mao ("112 pixels serve") sao
        # chute: serviam nesta fonte e nesta tela, e cortavam "Apresentada em"
        # ao meio em qualquer outra.
        for nome in colunas:
            self.tabela.heading(nome, text=titulos[nome])
            minimo = visual.largura_do_texto(titulos[nome], visual.FONTE_MEDIA) + p(28)
            self.tabela.column(
                nome, width=minimo, minwidth=minimo, stretch=False,
                anchor="center" if nome in ("numero", "data") else "w")
        self.tabela.pack(side="left", fill="both", expand=True)
        self.tabela.bind("<Configure>", self._distribuir_colunas)

        # Cor por situacao: quem ja esta no SAPL sai do caminho visualmente.
        self.tabela.tag_configure("enviada", foreground=visual.CINZA_APAGADO,
                                  background="#f9fafb")
        self.tabela.tag_configure("fila", foreground="#111827")

        rolagem = ttk.Scrollbar(moldura, orient="vertical", command=self.tabela.yview)
        rolagem.pack(side="left", fill="y")
        self.tabela.configure(yscrollcommand=rolagem.set)

        self._montar_acoes_da_tabela()

    def _montar_acoes_da_tabela(self) -> None:
        """Tirar e devolver clicando na linha - para o que faixa nenhuma pega.

        A faixa resolve "da 1901 ate a 1945". Nao resolve as avulsas: a 1476 que
        foi cadastrada solta meses atras, tres numeros espalhados que voltaram
        do cartorio. Sem isto, uma unica indicacao ja enviada no meio do lote
        obrigava a conviver com ela na fila para sempre.

        "Devolver para a fila" e o caminho de volta que faltava: o Desfazer so
        alcanca a ULTIMA marcacao desta sessao, entao quem errasse o numero e
        fechasse o programa nao tinha mais como corrigir - a indicacao ficava
        marcada como cadastrada sem nunca ter entrado no SAPL, que e o pior
        estado possivel: some da fila e ninguem procura por ela de novo.
        """
        p = visual.px
        linha = ttk.Frame(self.corpo)
        linha.pack(fill="x", pady=(p(8), 0))
        ttk.Label(linha, text="Selecionadas na tabela:",
                  style="Ajuda.TLabel").pack(side="left")
        ttk.Button(linha, text="Tirar da fila",
                   command=self.tirar_selecionadas).pack(side="left", padx=p(8))
        ttk.Button(linha, text="Devolver para a fila",
                   command=self.devolver_selecionadas).pack(side="left")
        ttk.Label(linha, style="Ajuda.TLabel",
                  text="  (Ctrl e Shift selecionam várias)").pack(side="left")

    def _montar_placar(self, pai) -> None:
        """Os tres numeros que dizem onde o trabalho esta."""
        self.cartoes = {}
        # Da direita para a esquerda: "na fila" e o numero que a pessoa olha
        # primeiro, entao ele fica na ponta.
        for chave, rotulo, cor in (
            ("fila", "na fila", visual.AZUL_VIVO),
            ("enviadas", "no SAPL", visual.VERDE),
            ("prontas", "prontas", visual.AZUL),
        ):
            cartao, numero = visual.cartao_numero(pai, rotulo, cor)
            cartao.pack(side="right", padx=(visual.px(8), 0))
            self.cartoes[chave] = numero

    def _distribuir_colunas(self, evento) -> None:
        """Reparte a largura que sobra entre as colunas, por peso.

        Com larguras fixas, alargar a janela deixava uma faixa cinza morta a
        direita da tabela e a ementa continuava cortada no mesmo lugar.
        """
        minimos = sum(self.tabela.column(c, "minwidth") for c in self.pesos)
        sobra = max(0, evento.width - minimos - visual.px(4))
        total = sum(self.pesos.values()) or 1
        for nome, peso in self.pesos.items():
            minimo = self.tabela.column(nome, "minwidth")
            self.tabela.column(nome, width=minimo + round(sobra * peso / total))

    def _montar_fila(self) -> None:
        """De onde a fila comeca - e vale para os DOIS botoes de envio.

        Antes este campo morava na mesma linha do "Abrir o SAPL e preencher", e
        parecia coisa so do modo manual. Parecia, mas nunca foi: ele sempre
        cortou a fila dos dois. Num lote que vai da 400 a 301, quem parou na
        350 digitava 350, olhava o botao de automatico logo abaixo, e nao tinha
        como saber que aquele numero valia para ele tambem - entao o automatico
        ficava sem uso, porque parecia que ia recomecar da 400.

        Agora o campo tem caixa propria, dizendo a quem serve, e o resultado do
        corte aparece escrito ao lado enquanto se digita.
        """
        p = visual.px
        caixa = ttk.LabelFrame(self.corpo, text=" Fila de envio ", padding=p(12))
        caixa.pack(fill="x", pady=(p(10), 0))

        linha = ttk.Frame(caixa)
        linha.pack(fill="x")
        ttk.Label(linha, text="Começar do número:",
                  font=visual.FONTE_BOTAO).pack(side="left")
        self.var_inicio = tk.StringVar()
        tk.Entry(linha, textvariable=self.var_inicio, width=7,
                 font=visual.FONTE_GRANDE, justify="center").pack(side="left", padx=p(8))
        # Escrever no campo redesenha a faixa na hora: e a prova, na tela, de
        # que o corte pegou - sem ela a pessoa so descobre depois de clicar.
        self.var_inicio.trace_add("write", lambda *_: self._mostrar_faixa())

        self.botao = ttk.Button(linha, text="Abrir o SAPL e preencher",
                                command=self.comecar)
        self.botao.pack(side="right")

        self.rotulo_faixa = visual.fluido(ttk.Label(
            caixa, style="Ajuda.TLabel", justify="left", text=""), margem=p(40))
        self.rotulo_faixa.pack(anchor="w", fill="x", pady=(p(8), 0))

    def _mostrar_faixa(self) -> None:
        """Escreve, em portugues, o que os botoes de envio vao pegar."""
        itens = self._selecionadas(calado=True)
        if not itens:
            self.rotulo_faixa.configure(
                text="Nenhuma indicação na fila a partir desse número — "
                     "confira o número ou deixe em branco.",
                foreground=visual.VERMELHO)
            return
        primeira = f"{itens[0]['numero']}/{itens[0]['ano']}"
        ultima = f"{itens[-1]['numero']}/{itens[-1]['ano']}"
        fora = len(self.na_fila()) - len(itens)
        self.rotulo_faixa.configure(
            text=f"Vai da {primeira} até a {ultima} — {len(itens)} indicação(ões)"
                 + (f", deixando {fora} de fora." if fora else ".")
                 + "  Vale para os dois botões, o manual e o automático.",
            foreground=visual.CINZA_TEXTO)

    def _montar_ja_enviadas(self) -> None:
        """Tirar da fila o que voce ja cadastrou a mao - em qualquer lugar dela.

        O botao antigo se chamava "Já enviei até aqui" e tirava tudo que vinha
        ANTES de um numero. Isso serve para quem parou no meio de um lote e
        volta no dia seguinte, e so para isso. Quem ja mandou a mao a faixa
        1901-1945 e hoje trabalha na 901-1000 nao tinha o que digitar: as 45 ja
        cadastradas caem no MEIO da lista, e nao existe numero que as tire sem
        levar junto centenas que ainda faltam.

        Por isso agora sao dois numeros, de e ate. Deixar o "de" em branco
        recupera exatamente o comportamento antigo (do comeco da fila ate o
        numero) - o botao velho virou o caso facil deste, em vez de sumir.
        """
        p = visual.px
        caixa = ttk.LabelFrame(self.corpo, text=" Já cadastrei essas à mão ",
                               padding=p(12))
        caixa.pack(fill="x", pady=(p(10), 0))

        linha = ttk.Frame(caixa)
        linha.pack(fill="x")
        ttk.Label(linha, text="Tirar da fila da",
                  font=visual.FONTE_BOTAO).pack(side="left")
        self.var_marcar_de = tk.StringVar()
        tk.Entry(linha, textvariable=self.var_marcar_de, width=7,
                 font=visual.FONTE_GRANDE,
                 justify="center").pack(side="left", padx=p(8))
        ttk.Label(linha, text="até a",
                  font=visual.FONTE_BOTAO).pack(side="left")
        self.var_marcar_ate = tk.StringVar()
        tk.Entry(linha, textvariable=self.var_marcar_ate, width=7,
                 font=visual.FONTE_GRANDE,
                 justify="center").pack(side="left", padx=p(8))
        for var in (self.var_marcar_de, self.var_marcar_ate):
            var.trace_add("write", lambda *_: self._mostrar_previa())

        self.botao_ja_enviei = ttk.Button(
            linha, text="Tirar da fila", command=self.marcar_ja_enviadas)
        self.botao_ja_enviei.pack(side="left", padx=p(10))
        # So aparece depois de uma marcacao, e some quando ela e desfeita.
        self.botao_desfazer = ttk.Button(linha, text="Desfazer",
                                         command=self.desfazer_marcacao)

        self.rotulo_previa = visual.fluido(ttk.Label(
            caixa, style="Ajuda.TLabel", justify="left", text=""), margem=p(40))
        self.rotulo_previa.pack(anchor="w", fill="x", pady=(p(8), 0))

    def _faixa_marcada(self) -> list[dict]:
        """As indicacoes da fila que os dois campos nomeiam. Vazio se nao dao par."""
        de = self.var_marcar_de.get().strip()
        ate = self.var_marcar_ate.get().strip()
        if not (de or ate):
            return []
        return entre_numeros(
            self.na_fila(),
            int(de) if de.isdigit() else None,
            int(ate) if ate.isdigit() else None,
        )

    def _mostrar_previa(self) -> None:
        """Escreve, enquanto se digita, quais indicacoes o botao vai tirar.

        Nao e enfeite: este botao marca dezenas de indicacoes como cadastradas
        de uma vez, e uma marcada por engano some da fila sem nunca ter entrado
        no SAPL. Ver a faixa escrita ANTES de clicar e o que separa "tirei as
        45 que mandei" de "tirei 300 sem perceber".
        """
        de = self.var_marcar_de.get().strip()
        ate = self.var_marcar_ate.get().strip()
        if not (de or ate):
            self.rotulo_previa.configure(
                text="Digite a primeira e a última que você já cadastrou no "
                     "SAPL por fora do programa — elas saem da fila e param de "
                     "aparecer para envio. Deixando o primeiro campo em branco, "
                     "tira tudo desde o começo da fila.",
                foreground=visual.CINZA_TEXTO)
            return
        itens = self._faixa_marcada()
        if not itens:
            self.rotulo_previa.configure(
                text="Nenhuma indicação da fila nessa faixa — confira os "
                     "números na tabela abaixo.",
                foreground=visual.VERMELHO)
            return
        primeira = f"{itens[0]['numero']}/{itens[0]['ano']}"
        ultima = f"{itens[-1]['numero']}/{itens[-1]['ano']}"
        self.rotulo_previa.configure(
            text=f"Vai tirar da fila {len(itens)} indicação(ões), da {primeira} "
                 f"até a {ultima}, marcadas como já cadastradas por você.",
            foreground=visual.CINZA_TEXTO)

    def _montar_automatico(self) -> None:
        """A faixa do envio automatico: quantas, o botao, e o que ele faz."""
        p = visual.px
        caixa = ttk.LabelFrame(self.corpo, text=" Envio automático ", padding=p(12))
        caixa.pack(fill="x", pady=(p(12), 0))

        linha = ttk.Frame(caixa)
        linha.pack(fill="x")
        ttk.Label(linha, text="Quer enviar quantas?",
                  font=visual.FONTE_BOTAO).pack(side="left")
        self.var_quantidade = tk.StringVar()
        tk.Entry(linha, textvariable=self.var_quantidade, width=6,
                 font=visual.FONTE_GRANDE, justify="center").pack(side="left", padx=p(10))
        self.botao_todas = ttk.Button(linha, text="todas", width=7,
                                      command=self._preencher_todas)
        self.botao_todas.pack(side="left")

        self.botao_auto = ttk.Button(linha, text="Enviar automático ▶",
                                     style="Principal.TButton",
                                     command=self.comecar_automatico)
        self.botao_auto.pack(side="right")

        # Andamento do envio: so aparece durante a sessao automatica. E a peca
        # que responde "quanto falta" sem a pessoa ter de contar linha.
        self.andamento = ttk.Frame(caixa)
        self.barra = ttk.Progressbar(self.andamento, mode="determinate",
                                     maximum=100,
                                     style="Envio.Horizontal.TProgressbar")
        self.barra.pack(fill="x")
        self.rotulo_andamento = ttk.Label(self.andamento, style="Ajuda.TLabel",
                                          text="")
        self.rotulo_andamento.pack(anchor="w", pady=(p(4), 0))

        self.rotulo_auto = visual.fluido(ttk.Label(
            caixa, style="Ajuda.TLabel", justify="left",
            text="O programa preenche E SALVA no SAPL sozinho, uma atrás da "
                 "outra, até completar essa quantidade. Ele para e chama você "
                 "em qualquer indicação que tenha pendência — e nunca cadastra "
                 "duas vezes a mesma."), margem=p(40))
        self.rotulo_auto.pack(anchor="w", fill="x", pady=(p(8), 0))

    def _montar_painel(self) -> None:
        """O que fica na tela enquanto o navegador esta aberto."""
        p = visual.px
        self.painel = ttk.LabelFrame(self.corpo, text=" Indicação na tela do SAPL ",
                                     padding=p(14))

        self.painel_titulo = ttk.Label(self.painel, text="", style="Titulo.TLabel")
        self.painel_titulo.pack(anchor="w")
        self.painel_autor = visual.fluido(
            ttk.Label(self.painel, text="", style="Ajuda.TLabel", justify="left"),
            margem=p(40))
        self.painel_autor.pack(anchor="w", fill="x", pady=(p(2), p(10)))

        pendencias = ttk.Frame(self.painel)
        pendencias.pack(fill="x")

        # Nem campo de data nem de anexo aqui: o programa preenche os dois no
        # formulario do SAPL. Digitar aqui para copiar la seria trabalho
        # dobrado e uma chance a mais de errar na transcricao. Esta linha e so
        # para CONFERIR o que foi preenchido.
        linha_data = ttk.Frame(pendencias)
        linha_data.pack(fill="x", pady=(0, p(6)))
        ttk.Label(linha_data, text="Data preenchida:",
                  font=visual.FONTE_BOTAO).pack(side="left")
        self.rotulo_data = ttk.Label(linha_data, text="", font=visual.FONTE_GRANDE)
        self.rotulo_data.pack(side="left", padx=p(8))

        linha_pdf = ttk.Frame(pendencias)
        linha_pdf.pack(fill="x")
        ttk.Label(linha_pdf, text="PDF anexado:",
                  font=visual.FONTE_BOTAO).pack(side="left")
        self.rotulo_pdf = ttk.Label(linha_pdf, text="", style="Ajuda.TLabel")
        self.rotulo_pdf.pack(side="left", padx=p(8))
        ttk.Button(linha_pdf, text="Abrir a pasta",
                   command=self.abrir_pasta_pdf).pack(side="left")

        self.caixa_recado = visual.aviso(self.painel, "", "atencao")

        botoes = ttk.Frame(self.painel)
        botoes.pack(fill="x", pady=(p(14), 0))
        self.botao_proxima = ttk.Button(botoes, text="Próxima indicação ▶",
                                        style="Principal.TButton",
                                        command=lambda: self.responder("proxima"))
        self.botao_proxima.pack(side="left")
        ttk.Button(botoes, text="Parar",
                   command=lambda: self.responder("parar")).pack(side="left", padx=p(8))
        self.botao_tentar = ttk.Button(botoes, text="Tentar de novo",
                                       command=lambda: self.responder("tentar"))

    # ----------------------------------------------------------------- dados
    def recarregar(self) -> None:
        self.prontas = []
        arquivo = OUTPUT_DIR / "indicacoes.json"
        if arquivo.exists():
            try:
                dados = json.loads(arquivo.read_text(encoding="utf-8"))
                self.prontas = [i for i in dados.get("indicacoes", [])
                                if i.get("status") == "pronto"]
            except (json.JSONDecodeError, OSError):
                self.prontas = []

        try:
            self.enviadas = ler_enviados()
        except ValueError as e:
            # Registro de enviados ilegivel: sem ele nao ha como saber o que ja
            # foi cadastrado, e enviar as cegas cadastraria em dobro.
            self.enviadas = {}
            messagebox.showerror("Registro de envios danificado", str(e))

        self.tabela.delete(*self.tabela.get_children())
        for posicao, item in enumerate(self.prontas):
            identificador = f"{item['numero']}/{item['ano']}"
            envio = self.enviadas.get(identificador)
            self.tabela.insert(
                "", "end",
                # A linha PASSA A SE CHAMAR "1901/2023" na tabela. E o que
                # permite ir da linha clicada de volta a indicacao sem manter
                # um segundo indice em paralelo, que sairia do lugar a cada
                # recarga. A posicao entra como desempate porque um lote com a
                # mesma indicacao repetida faria a segunda insercao estourar -
                # dado errado nao pode virar tela que nao abre.
                iid=identificador if not self.tabela.exists(identificador)
                else f"{identificador}#{posicao}",
                tags=("enviada",) if envio else ("fila",),
                values=(identificador,
                        item.get("data_apresentacao") or "— não lida —",
                        item.get("autor_nome_sapl") or "?",
                        (item.get("ementa") or "")[:150],
                        self._situacao(envio)),
            )
        na_fila = len(self.na_fila())
        enviadas = len(self.prontas) - na_fila
        self.titulo.configure(text="Indicações prontas para o SAPL")
        self.cartoes["prontas"].configure(text=str(len(self.prontas)))
        self.cartoes["enviadas"].configure(text=str(enviadas))
        self.cartoes["fila"].configure(text=str(na_fila))
        estado = ["!disabled"] if na_fila else ["disabled"]
        self.botao.state(estado)
        self.botao_auto.state(estado)
        self.botao_ja_enviei.state(estado)
        self._conferir_atualidade()
        self._mostrar_faixa()
        self._mostrar_previa()

    @staticmethod
    def _situacao(envio: dict | None) -> str:
        """O que a tabela mostra na coluna Situação.

        "cadastrada" e "marcada por você" NAO sao a mesma coisa e nao podem
        aparecer iguais: a primeira o programa fez e conferiu na tela do SAPL;
        a segunda e a sua palavra de que ja tinha feito a mao. As duas tiram a
        indicacao da fila, so uma tem testemunha.
        """
        if not envio:
            return "● na fila"
        quando = str(envio.get("em") or "").replace("T", " ")[:16]
        if envio.get("origem") == DECLARADO:
            return "✓ marcada por você"
        return f"✓ cadastrada {quando}".strip()

    def na_fila(self) -> list[dict]:
        """As prontas que ainda NAO foram cadastradas.

        O filtro vale para os dois botoes, nao so para o automatico: depois de
        uma rodada automatica, reabrir no modo manual mostraria as mesmas
        indicacoes ja cadastradas, e salvar de novo criaria materia repetida.
        """
        return [i for i in self.prontas
                if f"{i['numero']}/{i['ano']}" not in self.enviadas]

    def _conferir_atualidade(self) -> str:
        """As correcoes da aba 2 ja chegaram no que esta nesta tela?

        config/correcoes.json e escrito na hora em que voce salva a conferencia;
        output/indicacoes.json so e reescrito quando o lote e processado. Se o
        primeiro for mais novo que o segundo, o que esta aqui e texto velho.
        Devolve o aviso (vazio quando esta tudo em dia).
        """
        indicacoes = OUTPUT_DIR / "indicacoes.json"
        if not (CORRECOES.exists() and indicacoes.exists()):
            self.caixa_velha.pack_forget()
            return ""
        try:
            atrasado = CORRECOES.stat().st_mtime > indicacoes.stat().st_mtime
        except OSError:
            atrasado = False
        if not atrasado:
            self.caixa_velha.pack_forget()
            return ""

        aviso = ("Você corrigiu indicações na aba 2 depois do último "
                 "processamento. O que está nesta lista ainda é o texto antigo "
                 "— processe o lote de novo na aba 1 antes de enviar.")
        self.caixa_velha.configure(text=aviso, bg=visual.VERMELHO_FUNDO,
                                   fg=visual.VERMELHO)
        self.caixa_velha.pack(fill="x", pady=(visual.px(10), 0),
                              after=self.titulo.master)
        return aviso

    def _preencher_todas(self) -> None:
        # "todas" = todas as que os botoes vao pegar DE FATO, ja com o corte do
        # "começar do número" aplicado. Contar a fila inteira aqui daria um
        # numero maior do que existe e a pessoa acharia que ia enviar mais.
        self.var_quantidade.set(str(len(self._selecionadas(calado=True))))

    def _selecionadas(self, calado: bool = False) -> list[dict]:
        """A fila que os dois botoes de envio vao percorrer.

        `calado` existe para o rotulo que se atualiza a cada tecla digitada:
        ele chama isto o tempo todo e nao pode abrir caixa de aviso no meio da
        digitacao (a pessoa digitando "350" passa por "3" e por "35").
        """
        itens = self.na_fila()
        inicio = self.var_inicio.get().strip()
        if inicio.isdigit():
            cortado = cortar_do_numero(itens, int(inicio))
            if cortado:
                return cortado
            if not calado:
                messagebox.showinfo(
                    "Número não encontrado",
                    f"Nenhuma indicação na fila a partir do número {inicio}. "
                    "Começando da primeira da lista.")
            return [] if calado else itens
        return itens

    # ---------------------------------------------------------------- acoes
    def marcar_ja_enviadas(self) -> None:
        """Tira da fila a FAIXA que voce ja cadastrou a mao.

        O problema que isto resolve: o programa so sabe das indicacoes que ELE
        cadastrou. Todas as que voce mandou a mao - meses de trabalho - sao
        invisiveis para ele, e voltavam para a fila em toda sessao. Digitar o
        numero onde parou resolvia a sessao de hoje e nada mais: amanha a fila
        voltava inteira, o placar contava errado e "todas" queria dizer "as 400
        de novo".

        Antes so dava para tirar o COMECO da fila, e por isso a faixa 1901-1945
        - cadastrada a mao no meio do acervo, com a 901-1000 sendo trabalhada
        hoje - nao tinha como sair: qualquer numero que a alcancasse levava
        junto centenas que ainda faltam enviar.

        Marcadas aqui, elas saem da fila para sempre - e ficam gravadas como
        "declarado", nao como "cadastrado pelo programa", porque ninguem viu
        isso acontecer: quem afirma e voce.
        """
        de = self.var_marcar_de.get().strip()
        ate = self.var_marcar_ate.get().strip()
        if not (de.isdigit() or ate.isdigit()):
            messagebox.showinfo(
                "Digite os números primeiro",
                "Escreva a primeira e a última indicação que você já cadastrou "
                "no SAPL por fora do programa.\n\nDeixando o primeiro campo em "
                "branco, tira tudo desde o começo da fila até o número que "
                "você escrever no segundo.")
            return

        faixa = self._faixa_marcada()
        if not faixa:
            messagebox.showinfo(
                "Faixa não encontrada",
                f"Nenhuma indicação da fila entre {de or 'o começo'} e "
                f"{ate or 'o fim'}. Confira os números na tabela abaixo — pode "
                "ser que essas já tenham saído da fila.")
            return

        self._marcar(faixa, "Marcar como já enviadas")

    def tirar_selecionadas(self) -> None:
        """Tira da fila as linhas marcadas na tabela - as avulsas."""
        itens = [i for i in self._selecao_da_tabela()
                 if f"{i['numero']}/{i['ano']}" not in self.enviadas]
        if not itens:
            messagebox.showinfo(
                "Selecione na tabela",
                "Clique na tabela abaixo nas indicações que você já cadastrou "
                "à mão (segure Ctrl para escolher várias) e clique aqui.\n\n"
                "As que já estão fora da fila não contam.")
            return
        self._marcar(itens, "Tirar da fila as selecionadas")

    def _marcar(self, itens: list[dict], titulo: str) -> None:
        """A gravacao em si - uma so, para a faixa e para a selecao.

        As duas terminam no mesmo lugar de proposito: sao duas maneiras de
        apontar as mesmas indicacoes, e uma segunda copia da confirmacao e da
        gravacao seria a chance de as duas divergirem no dia em que uma for
        corrigida.
        """
        primeira = f"{itens[0]['numero']}/{itens[0]['ano']}"
        ultima = f"{itens[-1]['numero']}/{itens[-1]['ano']}"
        quais = (f"a indicação {primeira}" if len(itens) == 1
                 else f"{len(itens)} indicação(ões), da {primeira} até a {ultima}")
        if not messagebox.askyesno(
            titulo,
            f"Vou tirar da fila {quais}, por você já ter cadastrado essas no "
            "SAPL.\n\nElas param de aparecer na fila e o programa não vai mais "
            "oferecer essas para envio.\n\nSe errar, dá para desfazer: o botão "
            "'Desfazer' aparece logo depois, e 'Devolver para a fila' funciona "
            "a qualquer momento.\n\nPode marcar?",
        ):
            return

        identificadores = [f"{i['numero']}/{i['ano']}" for i in itens]
        try:
            marcar_varias(identificadores, origem=DECLARADO)
        except (ValueError, OSError) as e:
            messagebox.showerror("Não deu para marcar", str(e))
            return

        self._ultimas_marcadas = identificadores
        self.botao_desfazer.pack(side="left", padx=visual.px(10))
        self.recarregar()
        self.app.atualizar_abas()

    def devolver_selecionadas(self) -> None:
        """Devolve para a fila o que foi tirado por engano - a qualquer hora.

        So devolve o que VOCE declarou. O que o programa cadastrou e confirmou
        na tela do SAPL fica: aquilo e registro publico consumado, e apaga-lo
        daqui nao desfaz o cadastro - so faz o programa oferecer a indicacao de
        novo e criar a segunda materia para o mesmo documento.
        """
        itens = self._selecao_da_tabela()
        declaradas, cadastradas = [], []
        for item in itens:
            identificador = f"{item['numero']}/{item['ano']}"
            envio = self.enviadas.get(identificador)
            if not envio:
                continue
            alvo = (cadastradas if envio.get("origem") == AUTOMATICO
                    else declaradas)
            alvo.append(identificador)

        if not declaradas:
            messagebox.showinfo(
                "Nada para devolver",
                "Selecione na tabela as indicações que saíram da fila por "
                "engano.\n\n"
                + ("As que você escolheu foram cadastradas pelo próprio "
                   "programa, que conferiu na tela do SAPL que a matéria "
                   "entrou. Essas não voltam para a fila: mandá-las de novo "
                   "criaria uma segunda matéria para o mesmo documento."
                   if cadastradas else
                   "As que você escolheu já estão na fila."))
            return

        aviso = ""
        if cadastradas:
            aviso = (f"\n\n{len(cadastradas)} das selecionadas foram "
                     "cadastradas pelo próprio programa e vão ficar de fora — "
                     "essas já são registro no SAPL.")
        if not messagebox.askyesno(
            "Devolver para a fila",
            f"Vou devolver {len(declaradas)} indicação(ões) para a fila. Elas "
            "voltam a aparecer para envio." + aviso + "\n\nPode devolver?",
        ):
            return

        quantos = esquecer(declaradas)
        self._ultimas_marcadas = [i for i in self._ultimas_marcadas
                                  if i not in declaradas]
        if not self._ultimas_marcadas:
            self.botao_desfazer.pack_forget()
        self.recarregar()
        self.app.atualizar_abas()
        messagebox.showinfo("Devolvidas",
                            f"{quantos} indicação(ões) voltaram para a fila.")

    def _selecao_da_tabela(self) -> list[dict]:
        """As indicacoes das linhas marcadas, na ordem em que estao na lista.

        A ordem vem de self.prontas, nao da ordem em que se clicou: e ela que a
        confirmacao usa para dizer "da 1901 ate a 1945", e clicar de baixo para
        cima nao pode inverter a frase.
        """
        escolhidas = set(self.tabela.selection())
        return [item for item in self.prontas
                if f"{item['numero']}/{item['ano']}" in escolhidas
                or any(iid.startswith(f"{item['numero']}/{item['ano']}#")
                       for iid in escolhidas)]

    def desfazer_marcacao(self) -> None:
        """Devolve para a fila o que a ultima marcacao tirou.

        So desfaz o que VOCE declarou nesta sessao. O que o programa cadastrou
        e confirmou na tela do SAPL nunca sai daqui por um clique - aquilo e
        registro de fato consumado, nao anotacao.
        """
        if not self._ultimas_marcadas:
            return
        quantos = esquecer(self._ultimas_marcadas)
        self._ultimas_marcadas = []
        self.botao_desfazer.pack_forget()
        self.recarregar()
        self.app.atualizar_abas()
        messagebox.showinfo("Desfeito",
                            f"{quantos} indicação(ões) voltaram para a fila.")

    def comecar(self) -> None:
        self._abrir_sessao(enviar=0)

    def comecar_automatico(self) -> None:
        """Envio automatico: confere a quantidade e pede confirmacao.

        A confirmacao nao e formalidade. Depois dela o programa cria registros
        publicos sem mais nenhuma pergunta, e nao existe desfazer - por isso o
        texto diz o numero e a palavra "salva", nao "envia".
        """
        itens = self._selecionadas()
        if not itens:
            return

        atrasado = self._conferir_atualidade()
        if atrasado:
            messagebox.showerror("Processe o lote de novo", atrasado)
            return

        bruto = self.var_quantidade.get().strip()
        if not bruto.isdigit() or int(bruto) < 1:
            messagebox.showwarning(
                "Quantas?",
                "Digite quantas indicações o programa deve enviar sozinho "
                f"(1 a {len(itens)}), ou clique em 'todas'.")
            return

        quantidade = min(int(bruto), len(itens))
        primeira = f"{itens[0]['numero']}/{itens[0]['ano']}"
        ultima = f"{itens[quantidade - 1]['numero']}/{itens[quantidade - 1]['ano']}"
        if not messagebox.askyesno(
            "Confirmar o envio automático",
            f"O programa vai CADASTRAR {quantidade} indicação(ões) no SAPL "
            f"sem parar para conferência, começando na {primeira} e indo até a "
            f"{ultima}.\n\nCada uma vira registro público — não há como "
            "desfazer pelo programa.\n\nPode enviar?",
        ):
            return
        self._abrir_sessao(enviar=quantidade)

    def _abrir_sessao(self, enviar: int) -> None:
        itens = self._selecionadas()
        if not itens:
            return
        if self.sessao and self.sessao.is_alive():
            messagebox.showinfo("Já está aberto",
                                "A janela do SAPL já está aberta.")
            return

        # O navegador e a unica peca que esta etapa exige. Em vez de deixar o
        # Playwright estourar um erro tecnico la dentro, avisa antes e leva a
        # pessoa para a tela que resolve com um botao.
        from src.ambiente import navegador_instalado

        if not navegador_instalado():
            if messagebox.askyesno(
                "Falta o navegador",
                "Esta etapa abre o Firefox para preencher o formulário, e ele "
                "ainda não foi baixado nesta máquina (cerca de 90 MB, uma vez "
                "só).\n\nIr para a tela de instalação agora?",
            ):
                self.app.ir_para_instalacao()
            return

        self.eventos = queue.Queue()
        self.comandos = queue.Queue()
        # side="bottom" + before=moldura: o painel entra ANTES da tabela na
        # ordem de empacotamento, entao pega o espaco de que precisa e sobra
        # para a tabela o que restar. So o side="bottom" nao bastava - o painel
        # e empacotado agora, depois da tabela, e era ele que era espremido: os
        # botoes "Próxima" e "Parar" ficavam com 1 pixel de altura.
        self.painel.pack(side="bottom", fill="x", pady=(visual.px(14), 0),
                         before=self.moldura)
        self.painel_titulo.configure(text="Abrindo o navegador...")
        self.painel_autor.configure(
            text="A primeira vez demora mais: o Firefox precisa iniciar.")
        self.caixa_recado.pack_forget()
        self.botao.state(["disabled"])
        self.botao_auto.state(["disabled"])

        if enviar:
            self.total_cota = enviar
            self.barra.configure(value=0)
            self.rotulo_andamento.configure(
                text=f"0 de {enviar} cadastradas nesta sessão")
            self.andamento.pack(fill="x", pady=(visual.px(10), 0))
        else:
            self.andamento.pack_forget()

        self.sessao = SessaoSAPL(itens, self.comandos, self.eventos, enviar=enviar)
        self.sessao.start()
        self.after(120, self._consumir)

    def responder(self, comando: str) -> None:
        if self.sessao and self.sessao.is_alive():
            if comando == "parar":
                self.sessao.parar()
            else:
                self.comandos.put(comando)
            self.botao_proxima.state(["disabled"])
            self.botao_tentar.pack_forget()

    def abrir_pasta_pdf(self) -> None:
        if not self.item_atual:
            return
        caminho = caminho_do_pdf(self.item_atual)
        if caminho.exists():
            self.app.abrir_no_explorador(caminho)
        else:
            messagebox.showinfo(
                "PDF não encontrado",
                f"O arquivo {caminho.name} não está mais em output\\pdfs.\n\n"
                "Se você já anexou esta indicação no SAPL e apagou o arquivo, "
                "está tudo certo — é assim que o programa entende que ela já "
                "foi enviada.")

    # -------------------------------------------------------------- eventos
    def _consumir(self, ultima: bool = False) -> None:
        for evento in escoar(self.eventos):
            self._tratar(evento)

        if self.sessao and self.sessao.is_alive():
            self.after(120, self._consumir)
        elif not ultima:
            # Mais uma volta depois de a thread morrer. Os ultimos eventos -
            # "fim" inclusive - podem ter entrado na fila logo DEPOIS do escoar
            # acima e logo ANTES de a thread encerrar; sem esta passada extra,
            # eles ficariam na fila para sempre e a tela nunca destravaria.
            self.after(120, lambda: self._consumir(ultima=True))

    def _tratar(self, evento: tuple) -> None:
        especie = evento[0]
        if especie == "abrindo":
            self.painel_titulo.configure(text="Abrindo o navegador...")
        elif especie == "login":
            self._pedir_login(evento[1])
        elif especie == "form_nao_achado":
            self._form_nao_achado(evento[1], evento[2])
        elif especie == "preenchida":
            self._preenchida(*evento[1:])
        elif especie == "enviada":
            self._enviada(*evento[1:])
        elif especie == "impedida":
            self._impedida(*evento[1:])
        elif especie == "erro_indicacao":
            self._erro_indicacao(*evento[1:])
        elif especie == "fim":
            self._fim(*evento[1:])
        elif especie == "erro":
            self._erro(evento[1], evento[2])

    def _pedir_login(self, url: str) -> None:
        self.painel_titulo.configure(text="Faça o login do SAPL")
        self.painel_autor.configure(
            text="A janela do Firefox abriu na tela de entrada. O programa "
                 "nunca digita senha — quem entra é você.")
        self.caixa_recado.configure(
            text="Entre com o seu usuário na janela do Firefox e depois clique "
                 "em 'Próxima indicação' aqui. Da próxima vez já abre logado.",
            bg=visual.AMARELO_FUNDO, fg="#92400e")
        self.caixa_recado.pack(fill="x", pady=(visual.px(12), 0))
        self.botao_proxima.configure(text="Já entrei, continuar ▶")
        self.botao_proxima.state(["!disabled"])

    def _form_nao_achado(self, url: str, rotas: list[str]) -> None:
        self.botao.state(["!disabled"])
        self.botao_auto.state(["!disabled"])
        messagebox.showerror(
            "O formulário não apareceu",
            f"O endereço configurado ({url}) não mostrou o formulário de "
            "cadastro.\n\nRotas de matéria visíveis com o seu login:\n"
            + ("\n".join(rotas) or "(nenhuma encontrada)")
            + "\n\nAjuste 'caminho_formulario' em config\\sapl_form.json.")

    def _cabecalho_do_item(self, item, indice, total) -> None:
        """A identificacao da indicacao no painel - igual em todos os casos."""
        self.item_atual = item
        self.painel.configure(text=f" Indicação {indice} de {total} ")
        self.painel_titulo.configure(text=f"Indicação {item['numero']}/{item['ano']}")
        self.painel_autor.configure(
            text=f"Autor: {item.get('autor_nome_sapl') or '?'} "
                 f"(id {item.get('autor_id')})")
        data = item.get("data_apresentacao") or ""
        self.rotulo_data.configure(
            text=data or "(em branco — confira na aba 2)",
            foreground="#111111" if data else visual.VERMELHO)
        caminho = caminho_do_pdf(item)
        self.rotulo_pdf.configure(
            text=caminho.name if caminho.is_file()
            else f"{caminho.name} (não está mais em output\\pdfs)")

    def _preenchida(self, item, falhas, notas, indice, total) -> None:
        self._cabecalho_do_item(item, indice, total)

        recados = [f"• {n}" for n in notas] + [f"• FALHA: {f}" for f in falhas]
        if recados:
            self.caixa_recado.configure(
                text="Confira antes de salvar:\n" + "\n".join(recados),
                bg=visual.AMARELO_FUNDO if not falhas else visual.VERMELHO_FUNDO,
                fg="#92400e" if not falhas else visual.VERMELHO)
            self.caixa_recado.pack(fill="x", pady=(visual.px(12), 0))
        else:
            self.caixa_recado.pack_forget()

        self.botao_proxima.configure(text="Próxima indicação ▶")
        self.botao_proxima.state(["!disabled"])
        self.botao_tentar.pack_forget()

    def _enviada(self, item, recado, indice, total, feitas, restam) -> None:
        """Cadastrada sozinha. Nao espera clique - so mostra e segue."""
        self._cabecalho_do_item(item, indice, total)
        self.painel_titulo.configure(
            text=f"✓ Indicação {item['numero']}/{item['ano']} — {recado}")
        self.caixa_recado.configure(
            text=f"{feitas} cadastrada(s) nesta sessão · faltam {restam} "
                 "para completar a quantidade pedida.",
            bg=visual.VERDE_FUNDO, fg=visual.VERDE_TEXTO)
        self.caixa_recado.pack(fill="x", pady=(visual.px(12), 0))
        if self.total_cota:
            self.barra.configure(value=feitas / self.total_cota * 100)
            self.rotulo_andamento.configure(
                text=f"{feitas} de {self.total_cota} cadastradas nesta sessão")
        self.botao_proxima.state(["disabled"])
        self.botao_tentar.pack_forget()

    def _impedida(self, item, travas, indice, total) -> None:
        """Barrada antes de abrir o formulario - o motivo e dos dados."""
        self._cabecalho_do_item(item, indice, total)
        self.painel_titulo.configure(
            text=f"Indicação {item['numero']}/{item['ano']} — não pode ir sozinha")
        self.caixa_recado.configure(
            text="Esta ficou de fora do automático:\n"
                 + "\n".join(f"• {t}" for t in travas),
            bg=visual.VERMELHO_FUNDO, fg=visual.VERMELHO)
        self.caixa_recado.pack(fill="x", pady=(visual.px(12), 0))
        self.botao_proxima.configure(text="Pular esta ▶")
        self.botao_proxima.state(["!disabled"])
        self.botao_tentar.pack_forget()

    def _erro_indicacao(self, item, mensagem, indice, total) -> None:
        self.item_atual = item
        self.painel_titulo.configure(
            text=f"Indicação {item['numero']}/{item['ano']} — deu problema")
        self.caixa_recado.configure(text=mensagem, bg=visual.VERMELHO_FUNDO,
                                    fg=visual.VERMELHO)
        self.caixa_recado.pack(fill="x", pady=(visual.px(12), 0))
        self.botao_proxima.configure(text="Pular esta ▶")
        self.botao_proxima.state(["!disabled"])
        self.botao_tentar.pack(side="left", padx=visual.px(8))

    def _fim(self, feitas: int, total: int, cadastradas: int = 0) -> None:
        self.botao.state(["!disabled"])
        self.botao_proxima.state(["disabled"])
        self.painel_titulo.configure(text="Sessão encerrada")
        self.painel_autor.configure(
            text=f"{feitas} de {total} indicações passaram pela tela"
                 + (f" · {cadastradas} cadastrada(s) no SAPL" if cadastradas else ""))
        self.caixa_recado.configure(
            text="Pode fechar a janela do Firefox. Para continuar de onde "
                 "parou, digite o número em 'Começar do número' e abra de novo.",
            bg=visual.VERDE_FUNDO, fg="#166534")
        self.caixa_recado.pack(fill="x", pady=(visual.px(12), 0))
        # Rele o registro de envios: a lista tem de mostrar como cadastradas as
        # que acabaram de ir, senao a proxima sessao ofereceria as mesmas.
        self.recarregar()
        self.app.atualizar_abas()

    def _erro(self, mensagem: str, detalhe: str) -> None:
        self.botao.state(["!disabled"])
        self.botao_auto.state(["!disabled"])
        self.painel_titulo.configure(text="Não deu para abrir o SAPL")
        self.caixa_recado.configure(text=mensagem, bg=visual.VERMELHO_FUNDO,
                                    fg=visual.VERMELHO)
        self.caixa_recado.pack(fill="x", pady=(visual.px(12), 0))
        messagebox.showerror("Não deu para abrir o SAPL", mensagem)
