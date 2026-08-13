"""Cores, fontes e estilos da interface.

Tudo num lugar so para a tela inteira mudar de aparencia mexendo aqui. As
escolhas seguem a tela de revisao que ja existia no navegador (azul da Camara,
verde para a acao principal), para quem ja usou nao estranhar.

Fonte grande de proposito: quem opera isso passa horas comparando texto
digitado com pagina escaneada.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

AZUL = "#1a2b4c"        # cabecalho
AZUL_CLARO = "#b9c4dc"  # texto secundario sobre o azul
VERDE = "#1a7a3c"       # acao principal (fazer, salvar)
VERDE_ESCURO = "#14602f"
CINZA_FUNDO = "#f4f4f6"
CINZA_BORDA = "#d1d5db"
CINZA_TEXTO = "#4b5563"
VERMELHO = "#991b1b"
VERMELHO_FUNDO = "#fee2e2"
AMARELO_FUNDO = "#fff4e5"
AMARELO_BORDA = "#f0c36d"
VERDE_FUNDO = "#dcfce7"
BRANCO = "#ffffff"

FONTE = ("Segoe UI", 10)
FONTE_MEDIA = ("Segoe UI", 11)
FONTE_GRANDE = ("Segoe UI", 13)
FONTE_TITULO = ("Segoe UI", 15, "bold")
FONTE_BOTAO = ("Segoe UI", 11, "bold")
FONTE_MONO = ("Consolas", 9)


def aplicar_estilos(raiz: tk.Tk) -> None:
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

    estilo.configure("TButton", font=FONTE, padding=(12, 7))
    estilo.map("TButton", background=[("active", "#e5e7eb")])

    estilo.configure("Principal.TButton", font=FONTE_BOTAO, foreground=BRANCO,
                     background=VERDE, padding=(18, 12), borderwidth=0)
    estilo.map("Principal.TButton",
               background=[("active", VERDE_ESCURO), ("disabled", "#9ca3af")])

    estilo.configure("Gigante.TButton", font=("Segoe UI", 14, "bold"),
                     foreground=BRANCO, background=VERDE, padding=(24, 18),
                     borderwidth=0)
    estilo.map("Gigante.TButton",
               background=[("active", VERDE_ESCURO), ("disabled", "#9ca3af")])

    estilo.configure("TNotebook", background=CINZA_FUNDO, borderwidth=0)
    estilo.configure("TNotebook.Tab", font=FONTE_MEDIA, padding=(18, 10))
    estilo.map("TNotebook.Tab",
               background=[("selected", BRANCO)],
               foreground=[("disabled", "#9ca3af")])

    estilo.configure("Treeview", font=FONTE, rowheight=26, fieldbackground=BRANCO)
    estilo.configure("Treeview.Heading", font=FONTE_MEDIA)
    estilo.configure("TProgressbar", background=VERDE, troughcolor=CINZA_BORDA)


def cabecalho(pai: tk.Widget, titulo: str, subtitulo: str = "") -> ttk.Frame:
    """Faixa azul do topo, igual em todas as telas."""
    faixa = ttk.Frame(pai, style="Cabecalho.TFrame", padding=(24, 14))
    ttk.Label(faixa, text=titulo, style="Cabecalho.TLabel").pack(anchor="w")
    if subtitulo:
        ttk.Label(faixa, text=subtitulo, style="CabecalhoSub.TLabel").pack(anchor="w")
    return faixa


def aviso(pai: tk.Widget, texto: str, especie: str = "atencao") -> tk.Label:
    """Caixa colorida de recado. especie: atencao | erro | ok."""
    cores = {
        "atencao": (AMARELO_FUNDO, "#92400e"),
        "erro": (VERMELHO_FUNDO, VERMELHO),
        "ok": (VERDE_FUNDO, "#166534"),
    }
    fundo, frente = cores.get(especie, cores["atencao"])
    return tk.Label(
        pai, text=texto, bg=fundo, fg=frente, font=FONTE_MEDIA,
        justify="left", anchor="w", padx=14, pady=10, wraplength=900,
    )
