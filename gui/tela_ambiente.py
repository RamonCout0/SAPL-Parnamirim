"""Tela 4: conferir a instalação e resolver o que faltar, sem terminal.

Esta tela existe para o programa nunca dizer "faltou uma dependência" e parar.
Ela mostra o que está pronto, o que falta, o que é opcional — e resolve o que
dá para resolver sozinha, com um botão.

O que é obrigatório é pouco: as abas de processar e conferir funcionam de
cara. O navegador só faz falta na hora de enviar ao SAPL, e é baixado aqui.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from src import ambiente

from . import visual
from .tarefas import escoar


class TelaAmbiente(ttk.Frame):
    def __init__(self, pai, app):
        super().__init__(pai, padding=visual.px(20))
        self.app = app
        self.fila: queue.Queue = queue.Queue()
        self.trabalhando = False
        self.pecas: list[ambiente.Peca] = []

        # A lista de pecas cresce conforme o que falta instalar, e o log de
        # download vem embaixo: em janela baixa, o botao "Preparar o que falta"
        # ficava fora da tela. Rolando, ele sempre esta a um scroll de
        # distancia.
        area, self.corpo = visual.area_rolavel(self)
        area.pack(fill="both", expand=True)

        ttk.Label(self.corpo, text="Instalação", style="Titulo.TLabel").pack(anchor="w")
        visual.fluido(ttk.Label(
            self.corpo, style="Ajuda.TLabel", justify="left",
            text="O que o programa precisa para funcionar. Nada aqui exige "
                 "abrir o prompt de comando: o que estiver faltando e puder "
                 "ser resolvido automaticamente, o botão abaixo resolve.",
        ), margem=visual.px(48)).pack(anchor="w", fill="x",
                                      pady=(visual.px(4), visual.px(16)))

        self.lista = ttk.Frame(self.corpo)
        self.lista.pack(fill="x")

        botoes = ttk.Frame(self.corpo)
        botoes.pack(fill="x", pady=(visual.px(18), 0))
        self.botao_preparar = ttk.Button(botoes, text="Preparar o que falta",
                                         style="Principal.TButton",
                                         command=self.preparar)
        self.botao_preparar.pack(side="left")
        ttk.Button(botoes, text="Verificar de novo",
                   command=self.verificar).pack(side="left", padx=visual.px(8))
        ttk.Button(botoes, text="Abrir a pasta do programa",
                   command=lambda: self.app.abrir_no_explorador(self._raiz())
                   ).pack(side="left")

        caixa = ttk.LabelFrame(self.corpo, text=" Andamento ", padding=visual.px(12))
        caixa.pack(fill="both", expand=True, pady=(visual.px(18), 0))
        moldura = ttk.Frame(caixa)
        moldura.pack(fill="both", expand=True)
        self.log = tk.Text(moldura, height=8, font=visual.FONTE_MONO, wrap="word",
                           bg="#111827", fg="#e5e7eb", relief="flat", padx=visual.px(10), pady=visual.px(8))
        self.log.pack(side="left", fill="both", expand=True)
        self.log.configure(state="disabled")
        rolagem = ttk.Scrollbar(moldura, orient="vertical", command=self.log.yview)
        rolagem.pack(side="left", fill="y")
        self.log.configure(yscrollcommand=rolagem.set)

        # A primeira verificacao NAO acontece aqui: verificar() no fim avisa a
        # janela para renumerar as abas, e neste ponto elas ainda nem foram
        # acrescentadas ao notebook - o Tk recusa com "is not managed by".
        # Quem chama e a janela, depois de montar tudo.

    @staticmethod
    def _raiz():
        from src.config import RAIZ

        return RAIZ

    # ------------------------------------------------------------- conferir
    def verificar(self) -> None:
        for filho in self.lista.winfo_children():
            filho.destroy()

        self.pecas = ambiente.conferir()
        for peca in self.pecas:
            self._desenhar_peca(peca)

        falta_obrigatoria = any(not p.ok and p.obrigatoria for p in self.pecas)
        estado = "!disabled" if falta_obrigatoria and not self.trabalhando else "disabled"
        self.botao_preparar.state([estado])
        self.app.atualizar_abas()

    def _desenhar_peca(self, peca: ambiente.Peca) -> None:
        cartao = tk.Frame(self.lista, bg=visual.BRANCO, padx=visual.px(14), pady=visual.px(10),
                          highlightbackground=visual.CINZA_BORDA, highlightthickness=1)
        cartao.pack(fill="x", pady=(0, visual.px(8)))

        simbolo, cor = {
            "ok": ("✓", "#166534"),
            "falta": ("!", visual.VERMELHO),
            "opcional": ("–", "#92400e"),
        }[peca.situacao]

        topo = tk.Frame(cartao, bg=visual.BRANCO)
        topo.pack(fill="x")
        tk.Label(topo, text=simbolo, bg=visual.BRANCO, fg=cor,
                 font=("Segoe UI", 14, "bold"), width=2).pack(side="left")
        tk.Label(topo, text=peca.nome, bg=visual.BRANCO,
                 font=visual.FONTE_BOTAO).pack(side="left")
        tk.Label(topo, text=f"— {peca.detalhe}", bg=visual.BRANCO,
                 fg=visual.CINZA_TEXTO, font=visual.FONTE).pack(side="left", padx=visual.px(6))

        if peca.como_resolver:
            visual.fluido(tk.Label(
                cartao, text=peca.como_resolver, bg=visual.BRANCO,
                fg=visual.CINZA_TEXTO, font=visual.FONTE, justify="left",
                anchor="w"), margem=visual.px(70)
            ).pack(fill="x", padx=(visual.px(30), 0))

    # ------------------------------------------------------------- preparar
    def preparar(self) -> None:
        if self.trabalhando:
            return
        self.trabalhando = True
        self.botao_preparar.state(["disabled"])
        self._escrever("Baixando o navegador (cerca de 90 MB). Isto leva "
                       "alguns minutos na primeira vez.")

        fila = self.fila

        def trabalho():
            # Roda fora da thread da janela: o download demora e a interface
            # nao pode congelar. A thread so poe texto na fila.
            ok = ambiente.instalar_navegador(lambda l: fila.put(("linha", l)))
            fila.put(("fim", ok))

        threading.Thread(target=trabalho, daemon=True).start()
        self.after(120, self._consumir)

    def _consumir(self) -> None:
        terminou = False
        for evento in escoar(self.fila):
            if evento[0] == "linha":
                self._escrever(evento[1])
            elif evento[0] == "fim":
                terminou = True
                self.trabalhando = False
                if evento[1]:
                    self._escrever("Pronto: o navegador está instalado.")
                else:
                    self._escrever(
                        "Não deu certo. Confira a conexão com a internet e "
                        "tente de novo — se o problema continuar, pode ser "
                        "bloqueio de rede do órgão.")
                self.verificar()

        if not terminou and self.trabalhando:
            self.after(120, self._consumir)

    def _escrever(self, texto: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
