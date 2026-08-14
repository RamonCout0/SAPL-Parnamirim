"""Cores, fontes e pecas visuais da interface.

Tudo num lugar so para a tela inteira mudar de aparencia mexendo aqui. As
escolhas seguem a tela de revisao que ja existia no navegador (azul da Camara,
verde para a acao principal), para quem ja usou nao estranhar.

Fonte grande de proposito: quem opera isso passa horas comparando texto
digitado com pagina escaneada.

DUAS COISAS QUE ESTA INTERFACE NAO PODE SUPOR
---------------------------------------------
1. Que a tela e grande. Ela roda em maquina de Camara, e 1366x768 e comum. Por
   isso nenhuma medida em pixel e escrita solta no codigo: passa por px(), que
   a converte na escala real da tela. E por isso os textos longos quebram na
   largura que TEM (ver fluido), nao numa largura que alguem chutou.

2. Que a tela e a 100%. Windows em 125% ou 150% e o padrao de notebook novo.
   Sem preparar_dpi(), o Windows amplia a janela como se fosse uma imagem e
   tudo fica borrado; com ela, o Tk desenha nitido e px() cuida do tamanho.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

AZUL = "#1a2b4c"        # cabecalho
AZUL_CLARO = "#b9c4dc"  # texto secundario sobre o azul
AZUL_VIVO = "#1d4ed8"   # numeros de destaque, foco
VERDE = "#1a7a3c"       # acao principal (fazer, salvar)
VERDE_ESCURO = "#14602f"
CINZA_FUNDO = "#f4f4f6"
CINZA_BORDA = "#d1d5db"
CINZA_TEXTO = "#4b5563"
CINZA_APAGADO = "#6b7280"
VERMELHO = "#991b1b"
VERMELHO_FUNDO = "#fee2e2"
AMARELO_FUNDO = "#fff4e5"
AMARELO_BORDA = "#f0c36d"
AMARELO_TEXTO = "#92400e"
VERDE_FUNDO = "#dcfce7"
VERDE_TEXTO = "#166534"
BRANCO = "#ffffff"

# Quanto um pixel "de projeto" vale nesta tela. 1.0 a 96 dpi (Windows a 100%),
# 1.5 a 144 dpi (150%). Recalculado em aplicar_estilos, quando ja existe uma
# janela para perguntar.
ESCALA = 1.0

FONTE = ("Segoe UI", 10)
FONTE_MEDIA = ("Segoe UI", 11)
FONTE_GRANDE = ("Segoe UI", 13)
FONTE_TITULO = ("Segoe UI", 15, "bold")
FONTE_BOTAO = ("Segoe UI", 11, "bold")
FONTE_NUMERO = ("Segoe UI", 22, "bold")
FONTE_MONO = ("Consolas", 9)


def px(medida: float) -> int:
    """Pixel de projeto -> pixel desta tela.

    Toda medida em pixel passa por aqui. Sem isso, numa tela a 150% os textos
    cresceriam (o Tk cuida das fontes sozinho) mas as caixas em volta nao - e
    o texto vazaria para fora de tudo.

    Zero continua zero: "sem espaco nenhum" e uma decisao de layout, nao uma
    medida para escalar. Arredondar para 1 pixel encostaria widgets que foram
    postos colados de proposito.
    """
    if medida <= 0:
        return 0
    return max(1, round(medida * ESCALA))


def preparar_dpi() -> None:
    """Avisa o Windows que a janela sabe se virar em tela de alta densidade.

    Tem de ser chamada ANTES de criar a janela. Sem ela, o Windows desenha a
    janela em 96 dpi e depois amplia a imagem: funciona, mas fica borrado.
    Falha em silencio de proposito - interface borrada e um problema; interface
    que nao abre e outro bem maior.
    """
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)   # system DPI aware
        return
    except Exception:
        pass
    try:
        from ctypes import windll

        windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def aplicar_estilos(raiz: tk.Tk) -> None:
    global ESCALA

    # winfo_fpixels("1i") = quantos pixels o sistema diz que cabem numa
    # polegada. 96 e a tela comum; 120 e 144 sao Windows a 125% e 150%.
    try:
        ESCALA = max(1.0, raiz.winfo_fpixels("1i") / 96.0)
    except tk.TclError:
        ESCALA = 1.0
    # Fonte em PONTOS: quem converte ponto em pixel e o Tk, por este fator.
    # Deixar isso com ele (em vez de multiplicar os tamanhos na mao) e o que
    # mantem o texto do tamanho certo em qualquer densidade de tela.
    raiz.tk.call("tk", "scaling", raiz.winfo_fpixels("1i") / 72.0)

    estilo = ttk.Style(raiz)
    # "clam" e o unico tema do Tk que respeita cor de fundo em botao no
    # Windows - com o tema padrao, botao colorido fica cinza do sistema.
    with_clam = "clam" in estilo.theme_names()
    estilo.theme_use("clam" if with_clam else estilo.theme_use())

    raiz.configure(bg=CINZA_FUNDO)
    estilo.configure(".", font=FONTE, background=CINZA_FUNDO)
    estilo.configure("TFrame", background=CINZA_FUNDO)
    estilo.configure("TLabel", background=CINZA_FUNDO, foreground="#222222")
    estilo.configure("TLabelframe", background=CINZA_FUNDO)
    estilo.configure("TLabelframe.Label", background=CINZA_FUNDO, font=FONTE_MEDIA)
    estilo.configure("TCheckbutton", background=CINZA_FUNDO)
    estilo.configure("TRadiobutton", background=CINZA_FUNDO)

    estilo.configure("Cartao.TFrame", background=BRANCO, relief="flat")
    estilo.configure("Cartao.TLabel", background=BRANCO)
    estilo.configure("Titulo.TLabel", font=FONTE_TITULO, background=CINZA_FUNDO)
    estilo.configure("Ajuda.TLabel", font=FONTE, foreground=CINZA_TEXTO)
    estilo.configure("Cabecalho.TFrame", background=AZUL)
    estilo.configure("Cabecalho.TLabel", background=AZUL, foreground=BRANCO,
                     font=FONTE_TITULO)
    estilo.configure("CabecalhoSub.TLabel", background=AZUL, foreground=AZUL_CLARO)

    estilo.configure("TButton", font=FONTE, padding=(px(12), px(7)))
    estilo.map("TButton", background=[("active", "#e5e7eb")])

    estilo.configure("Principal.TButton", font=FONTE_BOTAO, foreground=BRANCO,
                     background=VERDE, padding=(px(18), px(12)), borderwidth=0)
    estilo.map("Principal.TButton",
               background=[("active", VERDE_ESCURO), ("disabled", "#9ca3af")])

    estilo.configure("Gigante.TButton", font=("Segoe UI", 14, "bold"),
                     foreground=BRANCO, background=VERDE, padding=(px(24), px(18)),
                     borderwidth=0)
    estilo.map("Gigante.TButton",
               background=[("active", VERDE_ESCURO), ("disabled", "#9ca3af")])

    estilo.configure("TNotebook", background=CINZA_FUNDO, borderwidth=0)
    estilo.configure("TNotebook.Tab", font=FONTE_MEDIA, padding=(px(18), px(10)))
    estilo.map("TNotebook.Tab",
               background=[("selected", BRANCO)],
               foreground=[("disabled", "#9ca3af")],
               # As duas linhas abaixo travam a aba selecionada no lugar. Sem
               # elas o tema "clam" incha e desloca a aba escolhida, que passa
               # por cima do nome das vizinhas - as quatro abas ficavam com o
               # texto embaralhado bem na hora de escolher para onde ir.
               expand=[("selected", [0, 0, 0, 0])],
               padding=[("selected", (px(18), px(10)))])

    estilo.configure("Treeview", font=FONTE, rowheight=px(26),
                     fieldbackground=BRANCO)
    estilo.configure("Treeview.Heading", font=FONTE_MEDIA)
    estilo.configure("TProgressbar", background=VERDE, troughcolor=CINZA_BORDA)
    # Barra do envio automatico: mesma peca, cor de "isto esta indo para o
    # sistema oficial agora" em vez do verde de "terminou".
    estilo.configure("Envio.Horizontal.TProgressbar", background=AZUL_VIVO,
                     troughcolor=CINZA_BORDA)


def dimensionar(janela: tk.Tk, largura: int = 1280, altura: int = 900) -> None:
    """Abre a janela do tamanho que CABE nesta tela, centralizada.

    Antes a janela nascia com 1200x880 fixos e minimo 1000x680. Num notebook de
    1366x768 - o que mais aparece em maquina de Camara - a janela ja abria mais
    alta que a tela, e a barra de tarefas comia os botoes de baixo: a pessoa
    nao conseguia clicar em "Salvar e continuar" sem arrastar a janela para
    cima primeiro.
    """
    tela_l, tela_a = janela.winfo_screenwidth(), janela.winfo_screenheight()
    # A margem deixa espaco para a barra de tarefas e para a janela nao colar
    # nas bordas - uma janela colada parece travada.
    larg = min(px(largura), tela_l - px(60))
    alt = min(px(altura), tela_a - px(90))
    x = max(0, (tela_l - larg) // 2)
    y = max(0, (tela_a - alt) // 3)   # um terco: parece centralizado ao olho
    janela.geometry(f"{larg}x{alt}+{x}+{y}")
    # Minimo baixo de proposito: e o tamanho em que tudo ainda e alcancavel,
    # nao o tamanho confortavel. Quem quiser trabalhar espremido, pode.
    janela.minsize(px(820), px(520))


def cabecalho(pai: tk.Widget, titulo: str, subtitulo: str = "") -> ttk.Frame:
    """Faixa azul do topo, igual em todas as telas."""
    faixa = ttk.Frame(pai, style="Cabecalho.TFrame", padding=(px(24), px(14)))
    ttk.Label(faixa, text=titulo, style="Cabecalho.TLabel").pack(anchor="w")
    if subtitulo:
        fluido(ttk.Label(faixa, text=subtitulo, style="CabecalhoSub.TLabel"),
               margem=px(48)).pack(anchor="w", fill="x")
    return faixa


def aviso(pai: tk.Widget, texto: str, especie: str = "atencao") -> tk.Label:
    """Caixa colorida de recado. especie: atencao | erro | ok."""
    cores = {
        "atencao": (AMARELO_FUNDO, AMARELO_TEXTO),
        "erro": (VERMELHO_FUNDO, VERMELHO),
        "ok": (VERDE_FUNDO, VERDE_TEXTO),
    }
    fundo, frente = cores.get(especie, cores["atencao"])
    return fluido(tk.Label(
        pai, text=texto, bg=fundo, fg=frente, font=FONTE_MEDIA,
        justify="left", anchor="w", padx=px(14), pady=px(10),
    ), margem=px(40))


def fluido(rotulo: tk.Widget, margem: int = 0) -> tk.Widget:
    """Faz o texto quebrar na largura que o widget TEM, e nao numa fixa.

    Era o defeito mais visivel ao encolher a janela: os textos de ajuda tinham
    wraplength escrito no codigo (980, 900, 620, 420 pixels). Numa janela mais
    estreita que isso, a linha nao quebrava - ela continuava do tamanho de
    antes e simplesmente saia pela direita, levando junto a largura minima da
    janela inteira, que entao nao encolhia mais.

    Ouvir o <Configure> do PAI (e nao do proprio rotulo) e o que evita o laco:
    mudar o wraplength muda o tamanho do rotulo, que dispararia outro
    <Configure> nele mesmo, sem fim.
    """
    margem = margem or px(24)

    def ajustar(evento) -> None:
        largura = max(evento.width - margem, px(140))
        if abs(largura - int(rotulo.cget("wraplength") or 0)) > px(8):
            rotulo.configure(wraplength=largura)

    rotulo.master.bind("<Configure>", ajustar, add="+")
    return rotulo


def area_rolavel(pai: tk.Widget) -> tuple[ttk.Frame, ttk.Frame]:
    """Uma area que ganha barra de rolagem SO quando o conteudo nao cabe.

    Devolve (caixa para empacotar, quadro onde por os widgets).

    E a resposta para a janela baixa. Sem isto, o Tk resolve a falta de altura
    escondendo widgets - e escondia justamente os campos de numero e de ementa
    da tela de conferencia, deixando na tela a imagem, os botoes e nenhum lugar
    para digitar. Rolar e sempre melhor do que sumir.
    """
    caixa = ttk.Frame(pai)
    # width/height 1: um Canvas nasce PEDINDO 378x265 pixels. Como ele e
    # empacotado com expand, esse pedido nao muda o tamanho final dele - mas
    # come o espaco da barra de rolagem, que ficava com 2 pixels de largura e
    # sumia da tela mesmo estando la. Pedindo quase nada, quem cresce e o
    # expand, e a barra fica com a largura dela.
    tela = tk.Canvas(caixa, highlightthickness=0, bg=CINZA_FUNDO,
                     width=1, height=1)
    barra = ttk.Scrollbar(caixa, orient="vertical", command=tela.yview)
    dentro = ttk.Frame(tela)
    janela = tela.create_window((0, 0), window=dentro, anchor="nw")
    tela.configure(yscrollcommand=barra.set)
    tela.pack(side="left", fill="both", expand=True)

    def conferir(_=None) -> None:
        tela.configure(scrollregion=tela.bbox("all"))
        precisa = dentro.winfo_reqheight() > tela.winfo_height()
        if precisa and not barra.winfo_ismapped():
            # before=tela: entra ANTES do canvas na ordem de empacotamento, e
            # por isso pega a largura dela antes de o canvas esticar.
            barra.pack(side="right", fill="y", before=tela)
        elif not precisa and barra.winfo_ismapped():
            barra.pack_forget()
            tela.yview_moveto(0)

    def ajustar() -> None:
        """Altura do quadro = a maior entre o que o conteudo pede e o que ha.

        Sobrando espaco, o quadro fica do tamanho da area e o que estiver
        marcado para esticar (o log, a tabela) estica como sempre esticou.
        Faltando espaco, o quadro fica do tamanho do conteudo e a barra aparece.
        """
        tela.itemconfigure(janela,
                           height=max(dentro.winfo_reqheight(), tela.winfo_height()))
        conferir()

    def ao_redimensionar(evento) -> None:
        # O quadro de dentro acompanha a largura da area: sem isto ele fica do
        # tamanho natural do conteudo e some para fora pela direita.
        tela.itemconfigure(janela, width=evento.width)
        ajustar()

    # Vigia o tamanho que o conteudo PEDE, e nao so o que ele tem.
    #
    # <Configure> avisa quando um widget MUDA DE TAMANHO. Como a altura do
    # quadro aqui e fixada por itemconfigure, acrescentar um widget dentro dele
    # nao muda tamanho nenhum: muda so o tamanho PEDIDO, em silencio. Foi assim
    # que o painel da indicacao, que so e empacotado quando a sessao do SAPL
    # comeca, entrou espremido em 135 pixels de um pedido de 347 - com os
    # botoes "Próxima" e "Parar" reduzidos a um pixel de altura, visiveis na
    # tela e impossiveis de clicar.
    ultimo = {"pedido": -1, "disponivel": -1, "agendado": None}

    def vigiar() -> None:
        if not caixa.winfo_exists():
            return
        pedido, disponivel = dentro.winfo_reqheight(), tela.winfo_height()
        if (pedido, disponivel) != (ultimo["pedido"], ultimo["disponivel"]):
            ultimo["pedido"], ultimo["disponivel"] = pedido, disponivel
            ajustar()
        ultimo["agendado"] = caixa.after(250, vigiar)

    def encerrar(evento) -> None:
        # Fechar a janela apaga o comando Python do lado do Tk, mas nao o
        # agendamento: sem cancelar, o Tk tenta chamar o que ja nao existe e
        # despeja um "invalid command name" no console na hora de sair.
        if evento.widget is caixa and ultimo["agendado"]:
            try:
                caixa.after_cancel(ultimo["agendado"])
            except tk.TclError:
                pass

    dentro.bind("<Configure>", conferir)
    tela.bind("<Configure>", ao_redimensionar)
    tela.bind("<MouseWheel>",
              lambda e: tela.yview_scroll(-e.delta // 120, "units"))
    caixa.bind("<Destroy>", encerrar)
    ultimo["agendado"] = caixa.after(250, vigiar)
    return caixa, dentro


def largura_do_texto(texto: str, fonte) -> int:
    """Quantos pixels este texto ocupa NESTA fonte, nesta tela.

    Serve para dimensionar coluna de tabela sem chutar: o chute funciona na
    maquina de quem escreveu e corta o cabecalho na de quem usa, que pode
    estar com outra escala de tela ou outra fonte de sistema.
    """
    from tkinter import font as tkfont

    try:
        return tkfont.Font(font=fonte).measure(texto)
    except tk.TclError:
        # Sem janela ainda: cai numa media grosseira em vez de estourar.
        return len(texto) * px(8)


def cartao_numero(pai: tk.Widget, rotulo: str, cor: str = AZUL) -> tuple[tk.Frame, tk.Label]:
    """Um numero grande com a legenda ao lado. Devolve (cartao, rotulo do numero).

    E para a pessoa saber onde esta o trabalho sem ler frase nenhuma: quantas
    prontas, quantas ja foram, quantas faltam.

    Numero e legenda lado a lado, e nao um embaixo do outro, por causa de altura:
    empilhados, os tres cartoes comiam 90 pixels da tela e, numa janela baixa,
    quem pagava a conta era a tabela - que encolhia ate sumir.
    """
    cartao = tk.Frame(pai, bg=BRANCO, padx=px(12), pady=px(6),
                      highlightbackground=CINZA_BORDA, highlightthickness=1)
    numero = tk.Label(cartao, text="0", bg=BRANCO, fg=cor, font=FONTE_NUMERO)
    numero.pack(side="left")
    tk.Label(cartao, text=rotulo, bg=BRANCO, fg=CINZA_TEXTO, font=FONTE,
             justify="left").pack(side="left", padx=(px(8), 0))
    return cartao, numero
