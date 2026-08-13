"""Tela 3: mandar as indicacoes prontas para o SAPL, uma a uma.

O programa abre o Firefox, preenche o que da para preencher e PARA. Voce
confere a tela, anexa o PDF, escreve a data e clica em salvar no SAPL - e
so entao aperta "Próxima" aqui.

Como a data e o anexo ficaram manuais (decisao do orgao), esta tela existe
para tirar o trabalho chato de perto: mostra a data pronta para copiar e
abre a pasta do PDF no lugar certo, sem a pessoa ter de procurar.
"""
from __future__ import annotations

import json
import queue
import tkinter as tk
from tkinter import messagebox, ttk

from src.config import OUTPUT_DIR
from src.sapl import caminho_do_pdf

from . import visual
from .sapl_worker import SessaoSAPL
from .tarefas import escoar


class TelaSAPL(ttk.Frame):
    def __init__(self, pai, app):
        super().__init__(pai, padding=16)
        self.app = app
        self.prontas: list[dict] = []
        self.eventos: queue.Queue = queue.Queue()
        self.comandos: queue.Queue = queue.Queue()
        self.sessao: SessaoSAPL | None = None
        self.item_atual: dict | None = None

        self._montar()
        self.recarregar()

    # --------------------------------------------------------------- layout
    def _montar(self) -> None:
        topo = ttk.Frame(self)
        topo.pack(fill="x")
        self.titulo = ttk.Label(topo, text="Indicações prontas", style="Titulo.TLabel")
        self.titulo.pack(side="left")

        filtros = ttk.Frame(self)
        filtros.pack(fill="x", pady=(10, 0))
        ttk.Label(filtros, text="Começar do número:").pack(side="left")
        self.var_inicio = tk.StringVar()
        tk.Entry(filtros, textvariable=self.var_inicio, width=10,
                 font=visual.FONTE_MEDIA, justify="center").pack(side="left", padx=8)
        ttk.Label(filtros, style="Ajuda.TLabel",
                  text="(em branco = começa da primeira da lista)").pack(side="left")

        self.botao = ttk.Button(filtros, text="Abrir o SAPL e preencher",
                                style="Principal.TButton", command=self.comecar)
        self.botao.pack(side="right")

        moldura = ttk.Frame(self)
        moldura.pack(fill="both", expand=True, pady=(12, 0))
        colunas = ("numero", "data", "autor", "ementa")
        self.tabela = ttk.Treeview(moldura, columns=colunas, show="headings", height=8)
        self.tabela.heading("numero", text="Indicação")
        self.tabela.heading("data", text="Apresentada em")
        self.tabela.heading("autor", text="Autor")
        self.tabela.heading("ementa", text="Ementa")
        self.tabela.column("numero", width=100, anchor="center")
        self.tabela.column("data", width=120, anchor="center")
        self.tabela.column("autor", width=200, anchor="w")
        self.tabela.column("ementa", width=540, anchor="w")
        self.tabela.pack(side="left", fill="both", expand=True)
        rolagem = ttk.Scrollbar(moldura, orient="vertical", command=self.tabela.yview)
        rolagem.pack(side="left", fill="y")
        self.tabela.configure(yscrollcommand=rolagem.set)

        self._montar_painel()

    def _montar_painel(self) -> None:
        """O que fica na tela enquanto o navegador esta aberto."""
        self.painel = ttk.LabelFrame(self, text=" Indicação na tela do SAPL ",
                                     padding=14)

        self.painel_titulo = ttk.Label(self.painel, text="", style="Titulo.TLabel")
        self.painel_titulo.pack(anchor="w")
        self.painel_autor = ttk.Label(self.painel, text="", style="Ajuda.TLabel")
        self.painel_autor.pack(anchor="w", pady=(2, 10))

        pendencias = ttk.Frame(self.painel)
        pendencias.pack(fill="x")

        # Nem campo de data nem de anexo aqui: o programa preenche os dois no
        # formulario do SAPL. Digitar aqui para copiar la seria trabalho
        # dobrado e uma chance a mais de errar na transcricao. Esta linha e so
        # para CONFERIR o que foi preenchido.
        linha_data = ttk.Frame(pendencias)
        linha_data.pack(fill="x", pady=(0, 6))
        ttk.Label(linha_data, text="Data preenchida:",
                  font=visual.FONTE_BOTAO).pack(side="left")
        self.rotulo_data = ttk.Label(linha_data, text="", font=visual.FONTE_GRANDE)
        self.rotulo_data.pack(side="left", padx=8)

        linha_pdf = ttk.Frame(pendencias)
        linha_pdf.pack(fill="x")
        ttk.Label(linha_pdf, text="PDF anexado:",
                  font=visual.FONTE_BOTAO).pack(side="left")
        self.rotulo_pdf = ttk.Label(linha_pdf, text="", style="Ajuda.TLabel")
        self.rotulo_pdf.pack(side="left", padx=8)
        ttk.Button(linha_pdf, text="Abrir a pasta",
                   command=self.abrir_pasta_pdf).pack(side="left")

        self.caixa_recado = visual.aviso(self.painel, "", "atencao")

        botoes = ttk.Frame(self.painel)
        botoes.pack(fill="x", pady=(14, 0))
        self.botao_proxima = ttk.Button(botoes, text="Próxima indicação ▶",
                                        style="Principal.TButton",
                                        command=lambda: self.responder("proxima"))
        self.botao_proxima.pack(side="left")
        ttk.Button(botoes, text="Parar",
                   command=lambda: self.responder("parar")).pack(side="left", padx=8)
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

        self.tabela.delete(*self.tabela.get_children())
        for item in self.prontas:
            self.tabela.insert(
                "", "end",
                values=(f"{item['numero']}/{item['ano']}",
                        item.get("data_apresentacao") or "— não lida —",
                        item.get("autor_nome_sapl") or "?",
                        (item.get("ementa") or "")[:150]),
            )
        self.titulo.configure(text=f"{len(self.prontas)} indicações prontas")
        self.botao.state(["!disabled"] if self.prontas else ["disabled"])

    def _selecionadas(self) -> list[dict]:
        itens = list(self.prontas)
        inicio = self.var_inicio.get().strip()
        if inicio.isdigit():
            alvo = int(inicio)
            cortado = [i for i in itens if i["numero"] <= alvo]
            if cortado:
                return cortado
            messagebox.showinfo(
                "Número não encontrado",
                f"Nenhuma indicação pronta com número menor ou igual a {alvo}. "
                "Começando da primeira da lista.")
        return itens

    # ---------------------------------------------------------------- acoes
    def comecar(self) -> None:
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
        self.painel.pack(fill="x", pady=(14, 0))
        self.painel_titulo.configure(text="Abrindo o navegador...")
        self.painel_autor.configure(
            text="A primeira vez demora mais: o Firefox precisa iniciar.")
        self.caixa_recado.pack_forget()
        self.botao.state(["disabled"])

        self.sessao = SessaoSAPL(itens, self.comandos, self.eventos)
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
    def _consumir(self) -> None:
        for evento in escoar(self.eventos):
            especie = evento[0]
            if especie == "abrindo":
                self.painel_titulo.configure(text="Abrindo o navegador...")
            elif especie == "login":
                self._pedir_login(evento[1])
            elif especie == "form_nao_achado":
                self._form_nao_achado(evento[1], evento[2])
            elif especie == "preenchida":
                self._preenchida(*evento[1:])
            elif especie == "erro_indicacao":
                self._erro_indicacao(*evento[1:])
            elif especie == "fim":
                self._fim(evento[1], evento[2])
            elif especie == "erro":
                self._erro(evento[1], evento[2])

        if self.sessao and self.sessao.is_alive():
            self.after(120, self._consumir)

    def _pedir_login(self, url: str) -> None:
        self.painel_titulo.configure(text="Faça o login do SAPL")
        self.painel_autor.configure(
            text="A janela do Firefox abriu na tela de entrada. O programa "
                 "nunca digita senha — quem entra é você.")
        self.caixa_recado.configure(
            text="Entre com o seu usuário na janela do Firefox e depois clique "
                 "em 'Próxima indicação' aqui. Da próxima vez já abre logado.",
            bg=visual.AMARELO_FUNDO, fg="#92400e")
        self.caixa_recado.pack(fill="x", pady=(12, 0))
        self.botao_proxima.configure(text="Já entrei, continuar ▶")
        self.botao_proxima.state(["!disabled"])

    def _form_nao_achado(self, url: str, rotas: list[str]) -> None:
        self.botao.state(["!disabled"])
        messagebox.showerror(
            "O formulário não apareceu",
            f"O endereço configurado ({url}) não mostrou o formulário de "
            "cadastro.\n\nRotas de matéria visíveis com o seu login:\n"
            + ("\n".join(rotas) or "(nenhuma encontrada)")
            + "\n\nAjuste 'caminho_formulario' em config\\sapl_form.json.")

    def _preenchida(self, item, falhas, notas, indice, total) -> None:
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

        recados = [f"• {n}" for n in notas] + [f"• FALHA: {f}" for f in falhas]
        if recados:
            self.caixa_recado.configure(
                text="Confira antes de salvar:\n" + "\n".join(recados),
                bg=visual.AMARELO_FUNDO if not falhas else visual.VERMELHO_FUNDO,
                fg="#92400e" if not falhas else visual.VERMELHO)
            self.caixa_recado.pack(fill="x", pady=(12, 0))
        else:
            self.caixa_recado.pack_forget()

        self.botao_proxima.configure(text="Próxima indicação ▶")
        self.botao_proxima.state(["!disabled"])
        self.botao_tentar.pack_forget()

    def _erro_indicacao(self, item, mensagem, indice, total) -> None:
        self.item_atual = item
        self.painel_titulo.configure(
            text=f"Indicação {item['numero']}/{item['ano']} — deu problema")
        self.caixa_recado.configure(text=mensagem, bg=visual.VERMELHO_FUNDO,
                                    fg=visual.VERMELHO)
        self.caixa_recado.pack(fill="x", pady=(12, 0))
        self.botao_proxima.configure(text="Pular esta ▶")
        self.botao_proxima.state(["!disabled"])
        self.botao_tentar.pack(side="left", padx=8)

    def _fim(self, feitas: int, total: int) -> None:
        self.botao.state(["!disabled"])
        self.botao_proxima.state(["disabled"])
        self.painel_titulo.configure(text="Sessão encerrada")
        self.painel_autor.configure(text=f"{feitas} de {total} indicações passaram pela tela.")
        self.caixa_recado.configure(
            text="Pode fechar a janela do Firefox. Para continuar de onde "
                 "parou, digite o número em 'Começar do número' e abra de novo.",
            bg=visual.VERDE_FUNDO, fg="#166534")
        self.caixa_recado.pack(fill="x", pady=(12, 0))

    def _erro(self, mensagem: str, detalhe: str) -> None:
        self.botao.state(["!disabled"])
        self.painel_titulo.configure(text="Não deu para abrir o SAPL")
        self.caixa_recado.configure(text=mensagem, bg=visual.VERMELHO_FUNDO,
                                    fg=visual.VERMELHO)
        self.caixa_recado.pack(fill="x", pady=(12, 0))
        messagebox.showerror("Não deu para abrir o SAPL", mensagem)
