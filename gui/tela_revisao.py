"""Tela 2: conferir o que a maquina nao leu com seguranca.

A pagina escaneada fica do lado esquerdo, do tamanho que der para ler, e os
campos do lado direito. E o ponto do pedido: nada de abrir planilha, nada de
procurar imagem em pasta - o papel e o formulario na mesma tela.

Uma indicacao so sai da fila quando TUDO que ela pede esta preenchido. O que
ainda falta aparece escrito em cima, em vermelho.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from src.config import carregar_ids
from src.pipeline import GLOSSARIO, REVISAO_DIR
from src.revisao import (
    ROTULO_DE,
    falta_em,
    ja_revisada,
    linhas_do_glossario,
    precisa_de,
    salvar_correcao,
)

from . import visual
from .estado import data_valida

IMAGENS_DIR = REVISAO_DIR / "imagens"
ZOOM_MIN, ZOOM_MAX, ZOOM_PASSO = 0.3, 3.0, 0.15


class TelaRevisao(ttk.Frame):
    def __init__(self, pai, app):
        super().__init__(pai, padding=16)
        self.app = app
        self.linhas: list[dict] = []
        self.indice = 0
        self.zoom = 1.0
        # Enquanto a pessoa nao mexer no zoom, cada pagina entra ajustada a
        # largura disponivel - que e como se le um documento. Depois de ela
        # escolher um zoom, respeitamos a escolha e nao ficamos remexendo.
        self._zoom_manual = False
        self._fotos: list = []          # referencia viva: o Tk nao segura sozinho
        self._autores: list[dict] = []

        self._montar()
        self.recarregar()

    # --------------------------------------------------------------- layout
    def _montar(self) -> None:
        topo = ttk.Frame(self)
        topo.pack(fill="x")
        self.titulo = ttk.Label(topo, text="", style="Titulo.TLabel")
        self.titulo.pack(side="left")
        self.contador = ttk.Label(topo, text="", style="Ajuda.TLabel")
        self.contador.pack(side="left", padx=14)

        nav = ttk.Frame(topo)
        nav.pack(side="right")
        ttk.Button(nav, text="◀ anterior", command=self.anterior).pack(side="left")
        ttk.Button(nav, text="próxima ▶", command=self.proxima).pack(side="left", padx=6)

        self.caixa_falta = visual.aviso(self, "", "erro")
        self.caixa_falta.pack(fill="x", pady=(12, 0))
        # Sem motivo (fila vazia), esta caixa some em vez de virar uma faixa
        # amarela vazia no meio da tela - ver _mostrar_motivo.
        self.caixa_motivo = visual.aviso(self, "", "atencao")

        self.corpo = ttk.Frame(self)
        self.corpo.pack(fill="both", expand=True, pady=(12, 0))
        self.corpo.columnconfigure(0, weight=3, minsize=420)
        self.corpo.columnconfigure(1, weight=2, minsize=380)
        self.corpo.rowconfigure(0, weight=1)

        self._montar_imagem(self.corpo)
        self._montar_campos(self.corpo)

    def _montar_imagem(self, pai) -> None:
        caixa = ttk.LabelFrame(pai, text=" Página escaneada ", padding=8)
        caixa.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        ferramentas = ttk.Frame(caixa)
        ferramentas.pack(fill="x", pady=(0, 8))
        ttk.Button(ferramentas, text="−", width=3,
                   command=lambda: self.mudar_zoom(-ZOOM_PASSO)).pack(side="left")
        ttk.Button(ferramentas, text="+", width=3,
                   command=lambda: self.mudar_zoom(ZOOM_PASSO)).pack(side="left", padx=4)
        ttk.Button(ferramentas, text="Ajustar à largura",
                   command=self.ajustar_largura).pack(side="left", padx=4)
        # A data mora no carimbo do verso, que fica na segunda pagina do
        # bloco. Rolar ate la a mao, em toda indicacao, seria o movimento mais
        # repetido da tela inteira.
        self.botao_carimbo = ttk.Button(ferramentas, text="Ir ao carimbo ↓",
                                        command=self.ir_ao_carimbo)
        self.botao_carimbo.pack(side="left", padx=4)
        ttk.Button(ferramentas, text="Abrir a imagem",
                   command=self.abrir_imagem).pack(side="left")

        moldura = ttk.Frame(caixa)
        moldura.pack(fill="both", expand=True)
        self.tela = tk.Canvas(moldura, bg="#e5e7eb", highlightthickness=0)
        self.tela.pack(side="left", fill="both", expand=True)
        barra_v = ttk.Scrollbar(moldura, orient="vertical", command=self.tela.yview)
        barra_v.pack(side="left", fill="y")
        barra_h = ttk.Scrollbar(caixa, orient="horizontal", command=self.tela.xview)
        barra_h.pack(fill="x")
        self.tela.configure(yscrollcommand=barra_v.set, xscrollcommand=barra_h.set)
        # Roda do mouse rola a imagem: e como a pessoa espera ler uma pagina.
        self.tela.bind("<MouseWheel>",
                       lambda e: self.tela.yview_scroll(-e.delta // 120, "units"))

    def _montar_campos(self, pai) -> None:
        caixa = ttk.Frame(pai)
        caixa.grid(row=0, column=1, sticky="nsew")

        # Ordem de empacotamento pensada para janela pequena: tudo que a pessoa
        # PRECISA alcancar (os botoes, principalmente) e preso embaixo primeiro,
        # e a caixa de ementa fica com o espaco que sobrar. Empacotando na
        # ordem visual, o botao "Salvar" era o primeiro a sair da tela quando
        # a janela nao era alta o bastante - justamente o que nao pode faltar.
        self.rodape = ttk.Label(caixa, style="Ajuda.TLabel", wraplength=420,
                                justify="left", text="")
        self.rodape.pack(side="bottom", anchor="w", pady=(12, 0))

        botoes = ttk.Frame(caixa)
        botoes.pack(side="bottom", fill="x", pady=(16, 0))
        ttk.Button(botoes, text="Salvar e continuar", style="Principal.TButton",
                   command=self.salvar).pack(side="left")
        ttk.Button(botoes, text="Pular por enquanto",
                   command=self.pular).pack(side="left", padx=8)

        self.ajuda_conferi = ttk.Label(
            caixa, style="Ajuda.TLabel", wraplength=420, justify="left",
            text="Marque quando o aviso for só sobre número deduzido ou página "
                 "única — esses não têm texto para corrigir.")
        self.ajuda_conferi.pack(side="bottom", anchor="w")

        self.var_conferi = tk.BooleanVar()
        self.caixa_conferi = ttk.Checkbutton(
            caixa, variable=self.var_conferi,
            text="Já conferi a página: número e páginas estão certos assim mesmo")
        self.caixa_conferi.pack(side="bottom", anchor="w", pady=(14, 2))

        self.rotulo_autor = ttk.Label(caixa, style="Ajuda.TLabel", wraplength=420,
                                      justify="left", text="")
        self.rotulo_autor.pack(side="bottom", anchor="w", pady=(4, 0))

        self.var_autor = tk.StringVar()
        self.campo_autor = ttk.Combobox(caixa, textvariable=self.var_autor,
                                        state="readonly", font=visual.FONTE_MEDIA)
        self.campo_autor.pack(side="bottom", fill="x")

        ttk.Label(caixa, text="Autor (vereador que assina)",
                  style="Titulo.TLabel").pack(side="bottom", anchor="w",
                                              pady=(16, 2))

        # Numero primeiro: quando o OCR destroi o cabecalho, e o campo que
        # impede a indicacao de ser cadastrada com o numero errado.
        linha_num = ttk.Frame(caixa)
        linha_num.pack(fill="x", pady=(0, 12))
        ttk.Label(linha_num, text="Número:", style="Titulo.TLabel").pack(side="left")
        self.var_numero = tk.StringVar()
        tk.Entry(linha_num, textvariable=self.var_numero, width=8,
                 font=visual.FONTE_GRANDE, justify="center").pack(side="left", padx=(8, 20))

        # A data e de CADA indicacao (48 datas diferentes num lote real de 196),
        # entao ela mora aqui, do lado do numero - nao numa configuracao do lote.
        ttk.Label(linha_num, text="Data:", style="Titulo.TLabel").pack(side="left")
        self.var_data = tk.StringVar()
        entrada_data = tk.Entry(linha_num, textvariable=self.var_data, width=12,
                                font=visual.FONTE_GRANDE, justify="center")
        entrada_data.pack(side="left", padx=8)
        entrada_data.bind("<KeyRelease>", self._formatar_data)

        self.rotulo_numero = ttk.Label(caixa, style="Ajuda.TLabel", text="",
                                       wraplength=420, justify="left")
        self.rotulo_numero.pack(anchor="w", pady=(0, 12))

        # O que sobrar de altura fica com a ementa.
        ttk.Label(caixa, text="Ementa", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(caixa, style="Ajuda.TLabel", wraplength=420, justify="left",
                  text="Já vem com o que a máquina leu. Compare com a imagem e "
                       "corrija o que estiver errado ou faltando.").pack(
            anchor="w", pady=(2, 6))
        moldura = ttk.Frame(caixa)
        moldura.pack(fill="both", expand=True)
        self.campo_ementa = tk.Text(moldura, height=6, wrap="word",
                                    font=visual.FONTE_MEDIA, relief="solid",
                                    borderwidth=1, padx=8, pady=6)
        self.campo_ementa.pack(side="left", fill="both", expand=True)
        rolagem = ttk.Scrollbar(moldura, orient="vertical",
                                command=self.campo_ementa.yview)
        rolagem.pack(side="left", fill="y")
        self.campo_ementa.configure(yscrollcommand=rolagem.set)

    # ----------------------------------------------------------------- dados
    def recarregar(self) -> None:
        """Rele o glossario do disco. Chamado depois de cada extracao."""
        self.linhas = linhas_do_glossario(GLOSSARIO)
        ids = carregar_ids()
        self._autores = sorted(
            (a for a in ids["autores"] if a.get("parlamentar")),
            key=lambda a: a["nome"],
        )
        self.campo_autor.configure(
            values=["— selecione o vereador —"] + [a["nome"] for a in self._autores])
        self.indice = self._primeira_pendente()
        self.mostrar()

    def _primeira_pendente(self) -> int:
        for i, linha in enumerate(self.linhas):
            if not ja_revisada(linha):
                return i
        return 0

    def pendentes(self) -> int:
        return sum(1 for l in self.linhas if not ja_revisada(l))

    @property
    def atual(self) -> dict | None:
        if 0 <= self.indice < len(self.linhas):
            return self.linhas[self.indice]
        return None

    # ------------------------------------------------------------- desenhar
    def mostrar(self) -> None:
        linha = self.atual
        if linha is None:
            self._mostrar_vazio()
            return

        # "numero" na planilha e sempre o que o OCR leu (a chave); o numero que
        # vale e o corrigido, quando existe.
        numero, ano = linha.get("numero", "?"), linha.get("ano", "?")
        corrigido = (linha.get("NUMERO_MANUAL") or "").strip()
        self.var_numero.set(corrigido or numero)
        self.var_data.set((linha.get("DATA_MANUAL") or "").strip()
                          or self._data_lida(linha))

        pistas = []
        if corrigido and corrigido != numero:
            self.titulo.configure(text=f"Indicação {corrigido}/{ano}")
            pistas.append(f"O OCR tinha lido o número {numero}.")
        else:
            self.titulo.configure(text=f"Indicação {numero}/{ano}")
        pistas.append(f"Data lida no papel: {linha.get('data_lida_pela_maquina') or '—'}")
        pistas.append("Os dois vão para o SAPL — confira na imagem.")
        self.rotulo_numero.configure(text="  ".join(pistas))
        self.contador.configure(
            text=f"{self.indice + 1} de {len(self.linhas)} · "
                 f"{self.pendentes()} ainda pendente(s)")

        falta = falta_em(linha)
        if falta:
            self.caixa_falta.configure(
                text="Ainda falta: " + ", ".join(ROTULO_DE[p] for p in falta),
                bg=visual.VERMELHO_FUNDO, fg=visual.VERMELHO)
        else:
            self.caixa_falta.configure(
                text="Esta indicação já está resolvida. Rode o processamento de "
                     "novo para ela entrar na fila do SAPL.",
                bg=visual.VERDE_FUNDO, fg="#166534")
        self._mostrar_motivo(linha.get("motivo") or "")

        self.campo_ementa.delete("1.0", "end")
        self.campo_ementa.insert(
            "1.0",
            (linha.get("EMENTA_MANUAL") or "").strip()
            or (linha.get("ementa_lida_pela_maquina") or "").strip())

        id_manual = (linha.get("AUTOR_ID_MANUAL") or "").strip()
        escolhido = next((a for a in self._autores if str(a["id"]) == id_manual), None)
        self.var_autor.set(escolhido["nome"] if escolhido else "— selecione o vereador —")

        pistas = []
        if linha.get("autor_lido_pela_maquina"):
            pistas.append(f"Lido no papel: {linha['autor_lido_pela_maquina']}")
        if linha.get("sugestao_ollama_autor"):
            pistas.append(f"Pista do modelo (conferir!): {linha['sugestao_ollama_autor']}")
        self.rotulo_autor.configure(
            text="\n".join(pistas) or "Nenhuma pista — leia o nome na imagem.")

        self.var_conferi.set(bool((linha.get("CONFIRMAR") or "").strip()))
        estrutural = precisa_de(linha) == ["confirmar"]
        self.ajuda_conferi.configure(
            text="Este aviso não tem ementa nem autor para corrigir: confira a "
                 "imagem e, se estiver tudo certo, marque a caixa acima."
            if estrutural else
            "Marque quando o aviso for só sobre número deduzido ou página "
            "única — esses não têm texto para corrigir.")

        self.rodape.configure(
            text=f"Páginas {linha.get('paginas', '?')} do arquivo original.")
        self._desenhar_imagens(linha)
        if not self._zoom_manual:
            # after() para o Tk ja ter calculado a largura real da area da
            # imagem - chamado agora, winfo_width() ainda devolve 1.
            self.after(60, lambda: self.ajustar_largura(manual=False))

    @staticmethod
    def _data_lida(linha: dict) -> str:
        """A data que a maquina leu, sem o "(plenario)" que a acompanha na
        planilha - a caixa de texto recebe so a data editavel."""
        bruta = (linha.get("data_lida_pela_maquina") or "").strip()
        return bruta.split(" (")[0] if "/" in bruta else ""

    def _formatar_data(self, evento) -> None:
        """Vai pondo as barras enquanto digita: 16122021 -> 16/12/2021."""
        if evento.keysym in ("BackSpace", "Delete", "Left", "Right", "Tab"):
            return
        so_digitos = "".join(c for c in self.var_data.get() if c.isdigit())[:8]
        partes = [so_digitos[:2], so_digitos[2:4], so_digitos[4:8]]
        novo = "/".join(p for p in partes if p)
        if novo != self.var_data.get():
            self.var_data.set(novo)
            evento.widget.icursor("end")

    def _mostrar_motivo(self, motivo: str) -> None:
        if motivo.strip():
            self.caixa_motivo.configure(text="Por que está aqui: " + motivo)
            self.caixa_motivo.pack(fill="x", pady=(8, 0), before=self.corpo)
        else:
            self.caixa_motivo.pack_forget()

    def _mostrar_vazio(self) -> None:
        self.titulo.configure(text="Nada para conferir")
        self.contador.configure(text="")
        self.caixa_falta.configure(
            text="Nenhuma indicação pendente. Processe um lote na primeira aba.",
            bg=visual.VERDE_FUNDO, fg="#166534")
        self.caixa_motivo.configure(text="")
        self.campo_ementa.delete("1.0", "end")
        self.var_autor.set("")
        self.tela.delete("all")
        self.rodape.configure(text="")

    def _desenhar_imagens(self, linha: dict) -> None:
        """Empilha as paginas do bloco numa unica area rolavel."""
        from PIL import Image, ImageTk

        self.tela.delete("all")
        self._fotos.clear()
        y = 0
        largura_max = 0
        for nome in (linha.get("imagens") or "").split(","):
            nome = nome.strip()
            if not nome:
                continue
            caminho = IMAGENS_DIR / nome
            if not caminho.is_file():
                continue
            try:
                with Image.open(caminho) as imagem:
                    largura = max(int(imagem.width * self.zoom), 1)
                    altura = max(int(imagem.height * self.zoom), 1)
                    reduzida = imagem.resize((largura, altura), Image.LANCZOS)
                    foto = ImageTk.PhotoImage(reduzida)
            except (OSError, ValueError):
                continue
            self._fotos.append(foto)          # sem isto a imagem some da tela
            self.tela.create_image(0, y, anchor="nw", image=foto)
            y += foto.height() + 10
            largura_max = max(largura_max, foto.width())

        if not self._fotos:
            self.tela.create_text(
                20, 20, anchor="nw", font=visual.FONTE_MEDIA, fill="#6b7280",
                text="(a imagem desta página não foi encontrada)\n\n"
                     "Processe o lote de novo na primeira aba para gerá-la.")
        self.tela.configure(scrollregion=(0, 0, largura_max, y))
        self.tela.yview_moveto(0)

    # ------------------------------------------------------------- acoes
    def mudar_zoom(self, delta: float) -> None:
        self.zoom = min(max(self.zoom + delta, ZOOM_MIN), ZOOM_MAX)
        self._zoom_manual = True
        if self.atual:
            self._desenhar_imagens(self.atual)

    def ajustar_largura(self, manual: bool = True) -> None:
        """Zoom que faz a pagina caber na largura disponivel."""
        from PIL import Image

        linha = self.atual
        if not linha:
            return
        primeira = next(
            (n.strip() for n in (linha.get("imagens") or "").split(",") if n.strip()),
            None,
        )
        if not primeira or not (IMAGENS_DIR / primeira).is_file():
            return
        try:
            with Image.open(IMAGENS_DIR / primeira) as imagem:
                largura_original = imagem.width
        except OSError:
            return
        disponivel = max(self.tela.winfo_width() - 20, 200)
        self.zoom = min(max(disponivel / largura_original, ZOOM_MIN), ZOOM_MAX)
        if manual:
            self._zoom_manual = True
        self._desenhar_imagens(linha)

    def ir_ao_carimbo(self) -> None:
        """Rola a imagem ate a segunda pagina do bloco - o verso, onde fica o
        carimbo "Lido na Sessão" com a data escrita a mao."""
        if len(self._fotos) < 2:
            return
        altura_total = sum(f.height() + 10 for f in self._fotos)
        if altura_total:
            self.tela.yview_moveto((self._fotos[0].height() + 10) / altura_total)

    def abrir_imagem(self) -> None:
        linha = self.atual
        if not linha:
            return
        primeira = next(
            (n.strip() for n in (linha.get("imagens") or "").split(",") if n.strip()),
            None,
        )
        if primeira and (IMAGENS_DIR / primeira).is_file():
            self.app.abrir_no_explorador(IMAGENS_DIR / primeira)
        else:
            messagebox.showinfo("Sem imagem",
                                "A imagem desta página ainda não foi gerada.")

    def salvar(self) -> None:
        linha = self.atual
        if not linha:
            return
        nome_autor = self.var_autor.get()
        autor = next((a for a in self._autores if a["nome"] == nome_autor), None)

        novo_numero = self.var_numero.get().strip()
        if novo_numero and not novo_numero.isdigit():
            messagebox.showwarning(
                "Número inválido",
                f"'{novo_numero}' não é um número. Digite só os algarismos — "
                "o 1.405 do papel se escreve 1405 aqui.")
            return

        nova_data = self.var_data.get().strip()
        if nova_data and not data_valida(nova_data):
            messagebox.showwarning(
                "Data inválida",
                f"'{nova_data}' não é uma data válida. Use dd/mm/aaaa — ou "
                "deixe em branco se não der para ler no papel.")
            return

        salvar_correcao(
            GLOSSARIO, linha.get("numero", ""), linha.get("ano", ""),
            numero_manual=novo_numero, data=nova_data,
            ementa=self.campo_ementa.get("1.0", "end").strip(),
            autor_id=str(autor["id"]) if autor else "",
            confirmado=self.var_conferi.get(),
        )
        self.linhas = linhas_do_glossario(GLOSSARIO)
        self.app.atualizar_abas()

        adiante = next((i for i, l in enumerate(self.linhas)
                        if i > self.indice and not ja_revisada(l)), None)
        if adiante is not None:
            self.indice = adiante
            self.mostrar()
            return

        restantes = self.pendentes()
        if restantes:
            self.indice = self._primeira_pendente()
            self.mostrar()
        else:
            self.mostrar()
            self._oferecer_reprocessar()

    def _oferecer_reprocessar(self) -> None:
        if messagebox.askyesno(
            "Tudo conferido",
            "Você resolveu todas as pendências.\n\n"
            "Para elas entrarem na fila do SAPL, o lote precisa ser processado "
            "de novo com as suas correções.\n\nProcessar agora?",
        ):
            self.app.processar_de_novo()

    def pular(self) -> None:
        adiante = next((i for i, l in enumerate(self.linhas)
                        if i > self.indice and not ja_revisada(l)), None)
        self.indice = adiante if adiante is not None else self._primeira_pendente()
        self.mostrar()

    def anterior(self) -> None:
        if self.indice > 0:
            self.indice -= 1
            self.mostrar()

    def proxima(self) -> None:
        if self.indice + 1 < len(self.linhas):
            self.indice += 1
            self.mostrar()
