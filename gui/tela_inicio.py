"""Tela 1: escolher os PDFs, dizer o ano e a data, e apertar um botao so.

E a tela que o usuario leigo enxerga como "o programa". Tudo que antes exigia
abrir o cmd e digitar `01_extrair.py` acontece aqui, com o andamento aparecendo
na propria janela em vez de num terminal preto.
"""
from __future__ import annotations

import queue
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from src.config import INPUT_DIR

from . import visual
from .tarefas import Tarefa, escoar


class TelaInicio(ttk.Frame):
    def __init__(self, pai, app):
        super().__init__(pai, padding=20)
        self.app = app
        self.fila: queue.Queue = queue.Queue()
        self.tarefa: Tarefa | None = None

        self._montar_arquivos()
        self._montar_opcoes()
        self._montar_acao()
        self._montar_andamento()
        self.atualizar_lista()

    # ------------------------------------------------------------------ PDFs
    def _montar_arquivos(self) -> None:
        caixa = ttk.LabelFrame(self, text=" 1. PDFs para processar ", padding=14)
        caixa.pack(fill="both", expand=False)

        colunas = ("arquivo", "tamanho")
        self.lista = ttk.Treeview(caixa, columns=colunas, show="headings", height=4)
        self.lista.heading("arquivo", text="Arquivo")
        self.lista.heading("tamanho", text="Tamanho")
        self.lista.column("arquivo", width=620, anchor="w")
        self.lista.column("tamanho", width=110, anchor="e")
        self.lista.pack(side="left", fill="both", expand=True)

        rolagem = ttk.Scrollbar(caixa, orient="vertical", command=self.lista.yview)
        rolagem.pack(side="left", fill="y")
        self.lista.configure(yscrollcommand=rolagem.set)

        botoes = ttk.Frame(caixa)
        botoes.pack(side="left", fill="y", padx=(14, 0))
        ttk.Button(botoes, text="Adicionar PDFs...",
                   command=self.adicionar).pack(fill="x", pady=(0, 6))
        ttk.Button(botoes, text="Tirar da lista",
                   command=self.remover).pack(fill="x", pady=(0, 6))
        ttk.Button(botoes, text="Abrir a pasta",
                   command=self.abrir_pasta).pack(fill="x")

    def atualizar_lista(self) -> None:
        self.lista.delete(*self.lista.get_children())
        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        for pdf in sorted(INPUT_DIR.glob("*.pdf")):
            mb = pdf.stat().st_size / (1024 * 1024)
            self.lista.insert("", "end", iid=pdf.name, values=(pdf.name, f"{mb:.1f} MB"))
        self._atualizar_botao()

    def adicionar(self) -> None:
        escolhidos = filedialog.askopenfilenames(
            title="Escolha os PDFs com as indicações",
            filetypes=[("Arquivos PDF", "*.pdf"), ("Todos", "*.*")],
        )
        copiados, repetidos = 0, []
        for caminho in escolhidos:
            origem = Path(caminho)
            destino = INPUT_DIR / origem.name
            if destino.exists():
                # Nao sobrescreve em silencio: pode ser um lote diferente com
                # o mesmo nome, e o original do usuario nao e nosso para
                # substituir sem perguntar.
                repetidos.append(origem.name)
                continue
            try:
                shutil.copy2(origem, destino)
                copiados += 1
            except OSError as e:
                messagebox.showerror("Não deu para copiar", f"{origem.name}\n\n{e}")
        self.atualizar_lista()
        if repetidos:
            messagebox.showinfo(
                "Já estavam na lista",
                "Estes arquivos já existem na pasta de entrada e foram "
                "mantidos como estavam:\n\n" + "\n".join(repetidos),
            )

    def remover(self) -> None:
        selecionados = self.lista.selection()
        if not selecionados:
            messagebox.showinfo("Nada selecionado",
                                "Clique no arquivo da lista que você quer tirar.")
            return
        if not messagebox.askyesno(
            "Tirar da lista",
            "Isto apaga a CÓPIA que está na pasta de entrada do programa "
            "(o seu arquivo original, de onde você copiou, continua onde "
            "está).\n\nTirar da lista?\n\n" + "\n".join(selecionados),
        ):
            return
        for nome in selecionados:
            try:
                (INPUT_DIR / nome).unlink()
            except OSError as e:
                messagebox.showerror("Não deu para apagar", f"{nome}\n\n{e}")
        self.atualizar_lista()

    def abrir_pasta(self) -> None:
        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.app.abrir_no_explorador(INPUT_DIR)

    # --------------------------------------------------------------- opcoes
    def _montar_opcoes(self) -> None:
        caixa = ttk.LabelFrame(self, text=" 2. Dados do lote ", padding=14)
        caixa.pack(fill="x", pady=(16, 0))

        linha = ttk.Frame(caixa)
        linha.pack(fill="x")

        ttk.Label(linha, text="Ano das indicações:").grid(row=0, column=0, sticky="w")
        self.var_ano = tk.StringVar(value=str(self.app.estado.ano))
        tk.Spinbox(linha, from_=2000, to=2100, textvariable=self.var_ano, width=8,
                   font=visual.FONTE_GRANDE, justify="center").grid(
            row=0, column=1, sticky="w", padx=(10, 30))

        # NAO existe campo de data aqui, de proposito: a data de apresentacao
        # e de CADA indicacao, nao do lote. Medido nos lotes reais: 48 datas
        # diferentes entre 196 indicacoes de um mesmo PDF - uma data unica
        # cadastraria quase todas errado. Ela e lida do fecho de cada
        # indicacao e aparece por indicacao nas abas 2 e 3.
        ttk.Label(
            linha, style="Ajuda.TLabel",
            text="A data de apresentação é lida de cada indicação, uma a uma.",
        ).grid(row=0, column=2, sticky="w")

        self.var_forcar_ano = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            caixa, variable=self.var_forcar_ano,
            text="Usar este ano para todos os arquivos, mesmo os que têm o ano "
                 "no nome (ex.: ..._201@2023.pdf)",
        ).pack(anchor="w", pady=(12, 0))

        self.var_ollama = tk.BooleanVar(value=self.app.estado.usar_ollama)
        ttk.Checkbutton(
            caixa, variable=self.var_ollama,
            text="Usar o Ollama para sugerir leituras difíceis (mais lento; "
                 "as sugestões nunca vão sozinhas para o SAPL)",
        ).pack(anchor="w", pady=(4, 0))

        self.var_force_pdfs = tk.BooleanVar(value=self.app.estado.usar_force_pdfs)
        ttk.Checkbutton(
            caixa, variable=self.var_force_pdfs,
            text="Forçar recriar PDFs (útil se arquivos foram apagados)",
        ).pack(anchor="w", pady=(4, 0))

        ttk.Label(
            caixa, style="Ajuda.TLabel", wraplength=980, justify="left",
            text="A data de cada indicação é lida do próprio documento (a linha "
                 "do Plenário, no fim do texto) e aparece pronta para copiar na "
                 "hora do envio. Onde o OCR não deixou ler, você preenche na "
                 "aba de conferência.",
        ).pack(anchor="w", pady=(10, 0))

    # ----------------------------------------------------------------- acao
    def _montar_acao(self) -> None:
        caixa = ttk.Frame(self)
        caixa.pack(fill="x", pady=(18, 0))
        self.botao = ttk.Button(caixa, text="FAZER TUDO", style="Gigante.TButton",
                                command=self.fazer_tudo)
        self.botao.pack(side="left")
        self.rotulo_botao = ttk.Label(
            caixa, style="Ajuda.TLabel", wraplength=620, justify="left",
            text="Separa as indicações uma a uma, lê ementa e autor, gera um "
                 "PDF de cada e mostra o que precisar da sua conferência.",
        )
        self.rotulo_botao.pack(side="left", padx=18)

    def _atualizar_botao(self) -> None:
        tem_pdf = bool(list(INPUT_DIR.glob("*.pdf"))) if INPUT_DIR.exists() else False
        rodando = self.tarefa is not None and self.tarefa.rodando()
        self.botao.state(["!disabled"] if tem_pdf and not rodando else ["disabled"])
        if not tem_pdf:
            self.rotulo_botao.configure(
                text="Adicione pelo menos um PDF na lista acima para começar.")

    # ------------------------------------------------------------ andamento
    def _montar_andamento(self) -> None:
        caixa = ttk.LabelFrame(self, text=" 3. Andamento ", padding=14)
        caixa.pack(fill="both", expand=True, pady=(18, 0))

        self.barra = ttk.Progressbar(caixa, mode="determinate", maximum=100)
        self.barra.pack(fill="x")
        self.status = ttk.Label(caixa, text="Pronto para começar.", style="Ajuda.TLabel")
        self.status.pack(anchor="w", pady=(6, 8))

        moldura = ttk.Frame(caixa)
        moldura.pack(fill="both", expand=True)
        # height=6 e o minimo que o Tk garante quando a janela e baixa; com um
        # valor maior, a caixa de log era a primeira coisa a ser cortada fora
        # da tela numa janela de 800px de altura.
        self.log = tk.Text(moldura, height=6, font=visual.FONTE_MONO, wrap="none",
                           bg="#111827", fg="#e5e7eb", relief="flat", padx=10, pady=8)
        self.log.pack(side="left", fill="both", expand=True)
        self.log.configure(state="disabled")
        rolagem = ttk.Scrollbar(moldura, orient="vertical", command=self.log.yview)
        rolagem.pack(side="left", fill="y")
        self.log.configure(yscrollcommand=rolagem.set)

    def _escrever_log(self, texto: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------- executar
    def fazer_tudo(self) -> None:
        if not self._validar():
            return
        self.app.estado.ano = int(self.var_ano.get())
        self.app.estado.usar_ollama = self.var_ollama.get()
        self.app.estado.salvar()

        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.barra.configure(value=0)
        self.status.configure(text="Processando...")
        self.botao.state(["disabled"])

        ano = self.app.estado.ano
        forcado = self.var_forcar_ano.get()
        ollama = self.app.estado.usar_ollama

        def trabalho():
            from src.pipeline import processar_pasta

            return processar_pasta(
                INPUT_DIR, ano_padrao=ano, ano_forcado=forcado,
                usar_ollama=ollama, gerar_pdfs=True,
                force_pdfs=self.var_force_pdfs.get(),
            )

        self.tarefa = Tarefa(trabalho, self.fila)
        self.tarefa.iniciar()
        self.after(80, self._consumir)

    def _validar(self) -> bool:
        if not list(INPUT_DIR.glob("*.pdf")):
            messagebox.showwarning("Faltam os PDFs",
                                   "Adicione pelo menos um PDF antes de começar.")
            return False
        if not self.var_ano.get().strip().isdigit():
            messagebox.showwarning("Ano inválido", "O ano tem de ser um número.")
            return False
        return True

    def _consumir(self) -> None:
        for evento in escoar(self.fila):
            especie = evento[0]
            if especie == "linha":
                self._escrever_log(evento[1])
            elif especie == "transitorio":
                self.status.configure(text=evento[1])
            elif especie == "progresso":
                rotulo, atual, total = evento[1], evento[2], evento[3]
                self.barra.configure(value=atual / total * 100)
                self.status.configure(text=f"{rotulo} {atual}/{total}")
            elif especie == "fim":
                self._terminou(evento[1])
            elif especie == "erro":
                self._falhou(evento[1], evento[2])

        if self.tarefa and self.tarefa.rodando():
            self.after(80, self._consumir)

    def _terminou(self, indicacoes) -> None:
        self.barra.configure(value=100)
        self.botao.state(["!disabled"])
        prontas = [i for i in indicacoes if i.status == "pronto"]
        revisao = [i for i in indicacoes if i.status == "revisao"]
        self.status.configure(
            text=f"{len(indicacoes)} indicações · {len(prontas)} prontas · "
                 f"{len(revisao)} para conferir")
        self._escrever_log("")
        self._escrever_log(f"=== {len(indicacoes)} indicações | {len(prontas)} prontas "
                           f"| {len(revisao)} para conferir ===")
        self.app.recarregar(indicacoes)

        if revisao:
            if messagebox.askyesno(
                "Falta conferir algumas",
                f"{len(revisao)} indicação(ões) precisam da sua conferência — "
                "o programa não manda para o SAPL nada que não conseguiu ler "
                "com segurança.\n\nAbrir a tela de conferência agora?",
            ):
                self.app.ir_para_revisao()
        elif prontas:
            messagebox.showinfo(
                "Tudo lido",
                f"As {len(prontas)} indicações foram lidas sem pendência.\n\n"
                "Pode ir para a aba de envio ao SAPL.")

    def _falhou(self, mensagem: str, detalhe: str) -> None:
        self.botao.state(["!disabled"])
        self.status.configure(text="Deu erro — veja o log abaixo.")
        self._escrever_log("")
        self._escrever_log("=== ERRO ===")
        for linha in detalhe.splitlines():
            self._escrever_log(linha)
        messagebox.showerror(
            "Não deu para processar",
            f"{mensagem}\n\nO detalhe completo está no log da tela.")
