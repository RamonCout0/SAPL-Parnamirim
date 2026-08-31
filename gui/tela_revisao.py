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

from src.config import PDFS_DIR, carregar_ids
from src.juncoes import cortar, juntar
from src.pipeline import GLOSSARIO, REVISAO_DIR
from src.revisao import (
    ROTULO_DE,
    falta_em,
    ja_revisada,
    linhas_do_glossario,
    ordenar_glossario,
    precisa_de,
    salvar_correcao,
)

from . import visual
from .estado import data_valida

IMAGENS_DIR = REVISAO_DIR / "imagens"

SELECIONE = "— selecione o vereador —"
# A resposta para as indicacoes assinadas por todos os vereadores ("Os
# Vereadores da Camara Municipal ... INDICAM", com paginas de assinaturas).
# E uma escolha, nao a ausencia dela: o programa so deixa passar sem autor
# quando VOCE marca isto aqui - ver sem_autor em src/pipeline.py.
SEM_AUTOR = "— esta indicação não tem autor individual —"
ZOOM_MIN, ZOOM_MAX, ZOOM_PASSO = 0.3, 3.0, 0.15

# Altura reservada para o rotulo "pagina N" acima de cada imagem empilhada.
# Fica numa constante porque duas contas dependem dela: a que desenha a pilha
# e a que rola ate o carimbo do verso.
ROTULO_PAGINA = 22


def _pagina_do_png(nome: str) -> str:
    """A pagina que o PNG mostra, tirada do proprio nome ("465-2023_pg077.png"
    -> "77").

    Do nome e nao da posicao na lista: um PNG que faltou na pasta faz a
    contagem por posicao errar todas as seguintes, e esse numero e o que a
    pessoa digita ao separar um bloco em dois - errado ali, o corte cai na
    pagina errada e parte a indicacao no meio.
    """
    partes = nome.rsplit("_pg", 1)
    if len(partes) != 2:
        return "?"
    digitos = partes[1].split(".")[0]
    return str(int(digitos)) if digitos.isdigit() else "?"


class TelaRevisao(ttk.Frame):
    def __init__(self, pai, app):
        super().__init__(pai, padding=visual.px(16))
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
        self.contador.pack(side="left", padx=visual.px(14))

        nav = ttk.Frame(topo)
        nav.pack(side="right")
        ttk.Button(nav, text="◀ anterior", command=self.anterior).pack(side="left")
        ttk.Button(nav, text="próxima ▶", command=self.proxima).pack(side="left", padx=visual.px(6))

        self.caixa_falta = visual.aviso(self, "", "erro")
        self.caixa_falta.pack(fill="x", pady=(visual.px(12), 0))
        # Sem motivo (fila vazia), esta caixa some em vez de virar uma faixa
        # amarela vazia no meio da tela - ver _mostrar_motivo.
        self.caixa_motivo = visual.aviso(self, "", "atencao")

        self.corpo = ttk.Frame(self)
        self.corpo.pack(fill="both", expand=True, pady=(visual.px(12), 0))
        self.corpo.columnconfigure(0, weight=3, minsize=visual.px(420))
        self.corpo.columnconfigure(1, weight=2, minsize=visual.px(380))
        self.corpo.rowconfigure(0, weight=1)

        self._montar_imagem(self.corpo)
        self._montar_campos(self.corpo)

    def _montar_imagem(self, pai) -> None:
        caixa = ttk.LabelFrame(pai, text=" Página escaneada ", padding=visual.px(8))
        caixa.grid(row=0, column=0, sticky="nsew", padx=(0, visual.px(14)))

        ferramentas = ttk.Frame(caixa)
        ferramentas.pack(fill="x", pady=(0, visual.px(8)))
        ttk.Button(ferramentas, text="−", width=3,
                   command=lambda: self.mudar_zoom(-ZOOM_PASSO)).pack(side="left")
        ttk.Button(ferramentas, text="+", width=3,
                   command=lambda: self.mudar_zoom(ZOOM_PASSO)).pack(side="left", padx=visual.px(4))
        ttk.Button(ferramentas, text="Ajustar à largura",
                   command=self.ajustar_largura).pack(side="left", padx=visual.px(4))
        # A data mora no carimbo do verso, que fica na segunda pagina do
        # bloco. Rolar ate la a mao, em toda indicacao, seria o movimento mais
        # repetido da tela inteira.
        self.botao_carimbo = ttk.Button(ferramentas, text="Ir ao carimbo ↓",
                                        command=self.ir_ao_carimbo)
        self.botao_carimbo.pack(side="left", padx=visual.px(4))
        ttk.Button(ferramentas, text="Abrir a imagem",
                   command=self.abrir_imagem).pack(side="left")
        # Abre o PDF FATIADO - o arquivo que vai ser anexado no SAPL, com as
        # paginas exatas deste bloco. As imagens ao lado mostram o mesmo
        # conteudo, mas so o PDF prova o que o SAPL vai receber.
        ttk.Button(ferramentas, text="Ver o PDF do SAPL",
                   command=self.abrir_pdf).pack(side="left", padx=visual.px(4))

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
        # Coluna rolavel, e os widgets na ordem em que se le e se preenche.
        #
        # A versao anterior prendia os botoes embaixo e ia empilhando o resto
        # por cima, para o "Salvar e continuar" nunca sair da tela numa janela
        # baixa. Funcionava para os botoes e falhava para o resto: numa janela
        # de 560 de altura, quem sumia eram os campos de NUMERO e de EMENTA -
        # sobrava a imagem, o botao de salvar e nada para digitar.
        #
        # Com a area rolavel nada some: falta altura, aparece a barra.
        area, caixa = visual.area_rolavel(pai)
        area.grid(row=0, column=1, sticky="nsew")

        # Numero primeiro: quando o OCR destroi o cabecalho, e o campo que
        # impede a indicacao de ser cadastrada com o numero errado.
        linha_num = ttk.Frame(caixa)
        linha_num.pack(fill="x", pady=(0, visual.px(12)))
        ttk.Label(linha_num, text="Número:", style="Titulo.TLabel").pack(side="left")
        self.var_numero = tk.StringVar()
        tk.Entry(linha_num, textvariable=self.var_numero, width=8,
                 font=visual.FONTE_GRANDE, justify="center").pack(side="left", padx=(visual.px(8), visual.px(20)))

        # A data e de CADA indicacao (48 datas diferentes num lote real de 196),
        # entao ela mora aqui, do lado do numero - nao numa configuracao do lote.
        ttk.Label(linha_num, text="Data:", style="Titulo.TLabel").pack(side="left")
        self.var_data = tk.StringVar()
        entrada_data = tk.Entry(linha_num, textvariable=self.var_data, width=12,
                                font=visual.FONTE_GRANDE, justify="center")
        entrada_data.pack(side="left", padx=visual.px(8))
        entrada_data.bind("<KeyRelease>", self._formatar_data)

        self.rotulo_numero = visual.fluido(ttk.Label(
            caixa, style="Ajuda.TLabel", text="", justify="left"))
        self.rotulo_numero.pack(anchor="w", fill="x", pady=(0, visual.px(12)))

        # O que sobrar de altura fica com a ementa.
        ttk.Label(caixa, text="Ementa", style="Titulo.TLabel").pack(anchor="w")
        visual.fluido(ttk.Label(
            caixa, style="Ajuda.TLabel", justify="left",
            text="Já vem com o que a máquina leu. Compare com a imagem e "
                 "corrija o que estiver errado ou faltando.")).pack(fill="x",
            anchor="w", pady=(visual.px(2), visual.px(6)))
        moldura = ttk.Frame(caixa)
        moldura.pack(fill="both", expand=True)
        self.campo_ementa = tk.Text(moldura, height=6, wrap="word",
                                    font=visual.FONTE_MEDIA, relief="solid",
                                    borderwidth=1, padx=visual.px(8), pady=visual.px(6))
        self.campo_ementa.pack(side="left", fill="both", expand=True)
        rolagem = ttk.Scrollbar(moldura, orient="vertical",
                                command=self.campo_ementa.yview)
        rolagem.pack(side="left", fill="y")
        self.campo_ementa.configure(yscrollcommand=rolagem.set)

        # --- autor ---
        ttk.Label(caixa, text="Autor (vereador que assina)",
                  style="Titulo.TLabel").pack(anchor="w",
                                              pady=(visual.px(16), visual.px(2)))
        self.var_autor = tk.StringVar()
        self.campo_autor = ttk.Combobox(caixa, textvariable=self.var_autor,
                                        state="readonly", font=visual.FONTE_MEDIA)
        self.campo_autor.pack(fill="x")

        self.rotulo_autor = visual.fluido(ttk.Label(
            caixa, style="Ajuda.TLabel", justify="left", text=""))
        self.rotulo_autor.pack(anchor="w", fill="x", pady=(visual.px(4), 0))

        # --- "ja conferi" ---
        self.var_conferi = tk.BooleanVar()
        self.caixa_conferi = ttk.Checkbutton(
            caixa, variable=self.var_conferi,
            text="Já conferi a página: número e páginas estão certos assim mesmo")
        self.caixa_conferi.pack(anchor="w", pady=(visual.px(14), visual.px(2)))

        self.ajuda_conferi = visual.fluido(ttk.Label(
            caixa, style="Ajuda.TLabel", justify="left",
            text="Marque quando o aviso for só sobre número deduzido ou página "
                 "única — esses não têm texto para corrigir."))
        self.ajuda_conferi.pack(anchor="w", fill="x")

        # --- acoes ---
        botoes = ttk.Frame(caixa)
        botoes.pack(fill="x", pady=(visual.px(16), 0))
        ttk.Button(botoes, text="Salvar e continuar", style="Principal.TButton",
                   command=self.salvar).pack(side="left")
        ttk.Button(botoes, text="Pular por enquanto",
                   command=self.pular).pack(side="left", padx=visual.px(8))

        # A saida para quando a maquina partiu uma indicacao em duas: aqui voce
        # olha a imagem, ve que este bloco e a continuacao do de cima, e manda
        # juntar. Ver src/juncoes.py.
        #
        # "no escaneamento" nao e detalhe: a juncao e gravada por (arquivo,
        # pagina), sempre foi, mas a tela agora anda em ordem NUMERICA e nao na
        # ordem das folhas. Dizer so "a anterior" mandaria olhar a tela de tras
        # - que pode ser outra indicacao, de outro PDF.
        self.botao_juntar = ttk.Button(
            caixa, text="Esta é continuação da folha de cima — juntar ↑",
            command=self.juntar_com_anterior)
        self.botao_juntar.pack(anchor="w", fill="x", pady=(visual.px(10), 0))
        self.ajuda_juntar = visual.fluido(ttk.Label(
            caixa, style="Ajuda.TLabel", justify="left",
            text="Use quando este bloco não for uma indicação nova e sim o "
                 "resto da que vem logo antes dele NO ESCANEAMENTO (uma folha "
                 "de anexo, um verso solto) — não a da tela anterior, que aqui "
                 "vem por ordem de número. As páginas passam para aquela "
                 "indicação e viram um PDF só."))
        self.ajuda_juntar.pack(anchor="w", fill="x", pady=(visual.px(2), 0))

        # O erro oposto, e o mais grave: a maquina NAO viu que uma indicacao
        # nova comecava no meio do bloco, entao duas viraram uma so. A de baixo
        # nao existe em lugar nenhum - nem no PDF, nem na fila do SAPL.
        # Ver src/juncoes.py.
        self.botao_separar = ttk.Button(
            caixa, text="Aqui começa outra indicação — separar ↓",
            command=self.separar_em_duas)
        self.botao_separar.pack(anchor="w", fill="x", pady=(visual.px(8), 0))
        self.ajuda_separar = visual.fluido(ttk.Label(
            caixa, style="Ajuda.TLabel", justify="left",
            text="Use quando estas páginas contiverem DUAS indicações — o "
                 "cabeçalho da segunda saiu ilegível e ela foi engolida por "
                 "esta. Role as imagens, veja em que página a outra começa e "
                 "informe o número dela. O bloco vira dois, cada um com o seu "
                 "PDF."))
        self.ajuda_separar.pack(anchor="w", fill="x", pady=(visual.px(2), 0))

        self.rodape = visual.fluido(ttk.Label(
            caixa, style="Ajuda.TLabel", justify="left", text=""))
        self.rodape.pack(anchor="w", fill="x", pady=(visual.px(12), 0))

    # ----------------------------------------------------------------- dados
    def recarregar(self) -> None:
        """Rele o glossario do disco. Chamado depois de cada extracao."""
        self.linhas = ordenar_glossario(linhas_do_glossario(GLOSSARIO))
        ids = carregar_ids()
        self._autores = sorted(
            (a for a in ids["autores"] if a.get("parlamentar")),
            key=lambda a: a["nome"],
        )
        self.campo_autor.configure(
            values=[SELECIONE, SEM_AUTOR] + [a["nome"] for a in self._autores])
        self.indice = self._primeira_pendente()
        self.mostrar()

    @staticmethod
    def _identidade(linha: dict) -> tuple:
        """Quem e ESTA linha, onde quer que ela esteja na lista.

        Numero LIDO, e nao o corrigido: o lido nunca muda, e e justamente ele
        que reencontra a linha depois de voce corrigir o numero. As paginas
        entram porque o mesmo numero lido se repete no lote - e o mesmo par que
        salvar_correcao() usa para nao gravar a correcao na linha errada.
        """
        return ((linha.get("numero") or "").strip(),
                (linha.get("ano") or "").strip(),
                (linha.get("paginas") or "").strip())

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
        if "numero" in precisa_de(linha):
            # Sem esta frase a pessoa nao tem como saber que deixar o numero
            # como esta tambem conta - e era justamente isso que prendia a
            # indicacao na fila para sempre.
            pistas.append("O número é o que está sendo perguntado aqui: se na "
                          "imagem ele estiver certo assim mesmo, deixe como "
                          "está e salve — isso confirma.")
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
        if escolhido:
            self.var_autor.set(escolhido["nome"])
        elif (linha.get("SEM_AUTOR") or "").strip():
            self.var_autor.set(SEM_AUTOR)
        else:
            self.var_autor.set(SELECIONE)

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
            self.caixa_motivo.pack(fill="x", pady=(visual.px(8), 0), before=self.corpo)
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
            # O numero da pagina, escrito acima da imagem. Nao e enfeite: e a
            # resposta para "em que pagina comeca a outra indicacao" na hora de
            # separar um bloco em dois. Sem ele so restava contar as imagens de
            # cima para baixo e torcer para nao ter pulado nenhuma.
            self.tela.create_text(
                visual.px(2), y, anchor="nw", font=visual.FONTE_BOTAO,
                fill=visual.CINZA_TEXTO, text=f"página {_pagina_do_png(nome)}")
            y += visual.px(ROTULO_PAGINA)

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
        rotulo = visual.px(ROTULO_PAGINA)
        altura_total = sum(f.height() + 10 + rotulo for f in self._fotos)
        if altura_total:
            self.tela.yview_moveto(
                (self._fotos[0].height() + 10 + rotulo) / altura_total)

    def abrir_pdf(self) -> None:
        """Abre o PDF fatiado desta indicacao - o que vai ser anexado."""
        linha = self.atual
        if not linha:
            return
        numero = (linha.get("NUMERO_MANUAL") or "").strip() or linha.get("numero", "")
        caminho = PDFS_DIR / f"{numero}-{linha.get('ano', '')}.pdf"
        if caminho.is_file():
            self.app.abrir_no_explorador(caminho)
            return
        messagebox.showinfo(
            "PDF ainda não existe",
            f"O arquivo {caminho.name} não está em output\\pdfs.\n\n"
            "Ele é gerado quando o lote é processado. Se você acabou de "
            "corrigir o número, processe de novo na primeira aba — o PDF "
            "passa a se chamar pelo número novo.")

    def juntar_com_anterior(self) -> None:
        """Marca este bloco como continuacao do de cima.

        A juncao nao muda nada agora: ela e gravada e vale na proxima rodada do
        pipeline, que e quem monta os blocos e fatia os PDFs. E o mesmo caminho
        das correcoes - por isso a tela oferece reprocessar logo em seguida.
        """
        linha = self.atual
        if not linha:
            return
        arquivo = (linha.get("arquivo") or "").strip()
        paginas = (linha.get("paginas") or "").strip()
        inicial = paginas.split("-")[0].strip()
        if not arquivo or not inicial.isdigit():
            messagebox.showinfo(
                "Falta a origem desta indicação",
                "Esta linha do glossário é de uma versão anterior do programa "
                "e não diz de qual PDF ela veio.\n\nProcesse o lote de novo na "
                "primeira aba e o botão passa a funcionar.")
            return

        if not messagebox.askyesno(
            "Juntar com a anterior",
            f"As páginas {paginas} deixam de ser uma indicação própria e "
            f"passam a fazer parte da indicação imediatamente acima delas no "
            f"arquivo {arquivo}.\n\n"
            "Vale a partir do próximo processamento, e fica gravado — não "
            "precisa refazer nas próximas vezes.\n\nJuntar?",
        ):
            return

        juntar(arquivo, int(inicial))
        if messagebox.askyesno(
            "Juntado",
            "Marcado. Para as páginas realmente passarem para a indicação de "
            "cima (e o PDF virar um só), o lote precisa ser processado de "
            "novo.\n\nProcessar agora?",
        ):
            self.app.processar_de_novo()

    @staticmethod
    def _faixa_de_paginas(linha: dict) -> tuple[int, int] | None:
        """(primeira, ultima) pagina do bloco, lidas da coluna "paginas".

        Um bloco de uma pagina so vem escrito "12", sem o traco - por isso a
        ultima cai de volta na primeira em vez de dar erro.
        """
        partes = [p.strip() for p in (linha.get("paginas") or "").split("-")]
        if not partes or not partes[0].isdigit():
            return None
        primeira = int(partes[0])
        ultima = int(partes[1]) if len(partes) > 1 and partes[1].isdigit() else primeira
        return primeira, ultima

    def separar_em_duas(self) -> None:
        """Marca que uma indicacao nova comeca no meio deste bloco.

        O caminho e o mesmo do juntar, e pelo mesmo motivo: quem monta os
        blocos e fatia os PDFs e o pipeline, entao a marcacao e gravada agora e
        vale na proxima rodada - por isso a tela oferece reprocessar em seguida.
        """
        linha = self.atual
        if not linha:
            return
        arquivo = (linha.get("arquivo") or "").strip()
        faixa = self._faixa_de_paginas(linha)
        if not arquivo or not faixa:
            messagebox.showinfo(
                "Falta a origem desta indicação",
                "Esta linha do glossário é de uma versão anterior do programa "
                "e não diz de qual PDF ela veio.\n\nProcesse o lote de novo na "
                "primeira aba e o botão passa a funcionar.")
            return

        primeira, ultima = faixa
        if ultima <= primeira:
            messagebox.showinfo(
                "Só há uma página",
                "Este bloco tem uma página só — não há onde separar.\n\nSe "
                "está faltando uma indicação no lote, ela foi engolida por "
                "outro bloco: procure o que estiver com páginas demais.")
            return

        escolha = self._pedir_corte(primeira, ultima)
        if not escolha:
            return
        pagina, numero = escolha

        if not messagebox.askyesno(
            "Separar em duas",
            f"A partir da página {pagina} começa a indicação {numero}.\n\n"
            f"As páginas {pagina} a {ultima} saem desta indicação e viram um "
            f"cadastro próprio, com PDF próprio. Esta aqui fica com as "
            f"páginas {primeira} a {pagina - 1}.\n\n"
            "Vale a partir do próximo processamento, e fica gravado — não "
            "precisa refazer nas próximas vezes.\n\nSeparar?",
        ):
            return

        cortar(arquivo, pagina, numero)
        if messagebox.askyesno(
            "Separado",
            "Marcado. Para o bloco virar dois de verdade — e os dois PDFs "
            "serem refeitos — o lote precisa ser processado de novo.\n\n"
            "Processar agora?",
        ):
            self.app.processar_de_novo()

    def _pedir_corte(self, primeira: int, ultima: int) -> tuple[int, int] | None:
        """Pergunta onde a outra indicacao comeca e qual e o numero dela.

        O numero e obrigatorio. Sem ele o bloco novo dependeria da deducao pela
        sequencia, e deducao que nao fecha faz o bloco ser DESCARTADO: as
        paginas sumiriam do lote justamente na operacao feita para nao
        perde-las (ver src/juncoes.py). Aqui nao ha o que deduzir - a imagem da
        pagina esta na tela, ao lado.
        """
        p = visual.px
        janela = tk.Toplevel(self)
        janela.title("Separar em duas indicações")
        janela.transient(self.winfo_toplevel())
        janela.resizable(False, False)
        corpo = ttk.Frame(janela, padding=p(16))
        corpo.pack(fill="both", expand=True)

        ttk.Label(corpo, style="Titulo.TLabel",
                  text="Em que página começa a outra indicação?").pack(anchor="w")
        # wraplength fixo (e nao visual.fluido) porque a janela nao e
        # redimensionavel: quem manda na largura aqui e este texto.
        ttk.Label(corpo, style="Ajuda.TLabel", justify="left", wraplength=p(430),
                  text=f"Este bloco vai da página {primeira} à {ultima} do "
                       f"arquivo original — são os números escritos acima de "
                       f"cada imagem, ao lado. Escolha a PRIMEIRA página da "
                       f"indicação de baixo."
                  ).pack(anchor="w", fill="x", pady=(p(4), p(10)))

        var_pagina = tk.StringVar(value=str(primeira + 1))
        tk.Spinbox(corpo, from_=primeira + 1, to=ultima, textvariable=var_pagina,
                   width=6, font=visual.FONTE_GRANDE, justify="center",
                   state="readonly").pack(anchor="w")

        ttk.Label(corpo, style="Titulo.TLabel", text="Número dessa indicação"
                  ).pack(anchor="w", pady=(p(14), p(2)))
        ttk.Label(corpo, style="Ajuda.TLabel", justify="left", wraplength=p(430),
                  text="Leia no papel, na imagem. Só os algarismos — o 1.405 "
                       "do papel se escreve 1405 aqui. É obrigatório: o "
                       "programa não pode adivinhar o número de um cabeçalho "
                       "que ele não conseguiu ler."
                  ).pack(anchor="w", fill="x")

        var_numero = tk.StringVar()
        campo = tk.Entry(corpo, textvariable=var_numero, width=8,
                         font=visual.FONTE_GRANDE, justify="center")
        campo.pack(anchor="w", pady=(p(6), 0))

        erro = tk.Label(corpo, text="", bg=visual.VERMELHO_FUNDO,
                        fg=visual.VERMELHO, font=visual.FONTE, anchor="w",
                        justify="left", padx=p(8), pady=p(6))

        resposta: dict = {}

        def confirmar(*_evento) -> None:
            numero = var_numero.get().strip()
            if not numero.isdigit() or int(numero) <= 0:
                erro.configure(
                    text="Digite o número da indicação — só algarismos.")
                erro.pack(fill="x", pady=(p(10), 0))
                campo.focus_set()
                return
            resposta["pagina"] = int(var_pagina.get())
            resposta["numero"] = int(numero)
            janela.destroy()

        botoes = ttk.Frame(corpo)
        botoes.pack(fill="x", pady=(p(16), 0))
        ttk.Button(botoes, text="Separar", style="Principal.TButton",
                   command=confirmar).pack(side="left")
        ttk.Button(botoes, text="Cancelar",
                   command=janela.destroy).pack(side="left", padx=p(8))

        campo.focus_set()
        janela.bind("<Return>", confirmar)
        janela.bind("<Escape>", lambda _e: janela.destroy())
        # A trava modal so pega com a janela ja desenhada - antes disso o Tk
        # recusa com "grab failed: window not viewable". Sem o try, essa recusa
        # derrubaria a janela inteira por causa do enfeite; sem a trava, a
        # janela continua funcionando, so nao bloqueia o resto da tela.
        janela.update_idletasks()
        try:
            janela.grab_set()
        except tk.TclError:
            pass
        self.wait_window(janela)
        if not resposta:
            return None
        return resposta["pagina"], resposta["numero"]

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
        sem_autor = nome_autor == SEM_AUTOR

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
            # As paginas dizem QUAL linha e esta, quando duas foram lidas com o
            # mesmo numero. Sem elas, corrigir a segunda gravava na primeira.
            paginas=linha.get("paginas", ""),
            numero_manual=novo_numero, data=nova_data,
            ementa=self.campo_ementa.get("1.0", "end").strip(),
            autor_id=str(autor["id"]) if autor else "",
            sem_autor=sem_autor,
            confirmado=self.var_conferi.get(),
        )
        # Reencontrar a linha por QUEM ELA E, e nao pela posicao que ela
        # ocupava. Em ordem numerica a posicao nao e estavel: corrigir uma 1958
        # que o OCR leu como 158 leva a linha da segunda tela para o meio da
        # lista, e continuar confiando no indice antigo faria a tela seguinte
        # falar de uma indicacao que voce nunca abriu - inclusive cobrando "o
        # que falta preencher" nela.
        alvo = self._identidade(self.atual) if self.atual else None
        self.linhas = ordenar_glossario(linhas_do_glossario(GLOSSARIO))
        if alvo is not None:
            self.indice = next(
                (i for i, l in enumerate(self.linhas)
                 if self._identidade(l) == alvo), self.indice)
        self.app.atualizar_abas()

        # Salvou e ainda falta coisa NESTA indicacao? Entao fica nela e diz o
        # que falta. Antes a tela pulava adiante em silencio e, como ela sempre
        # volta para a primeira pendente, a pessoa era jogada de volta aqui na
        # salvada seguinte sem entender por que - parecia que o programa
        # "travava" numa indicacao so.
        if self.atual is not None and not ja_revisada(self.atual):
            self.mostrar()
            messagebox.showwarning(
                "Ainda falta preencher",
                "Esta indicação continua pendente porque falta: "
                + ", ".join(ROTULO_DE[p] for p in falta_em(self.atual))
                + ".\n\nPreencha o que está faltando (está escrito em vermelho "
                  "no alto da tela) e salve de novo.")
            return

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
