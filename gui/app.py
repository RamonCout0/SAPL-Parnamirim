"""A janela: junta as tres telas e o que elas compartilham.

Ordem das abas = ordem do trabalho: processar, conferir o que ficou duvidoso,
mandar para o SAPL. O numero entre parenteses em cada aba diz quanto falta,
para a pessoa nunca precisar adivinhar onde ela parou.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import visual
from .estado import Estado
from .tela_ambiente import TelaAmbiente
from .tela_inicio import TelaInicio
from .tela_revisao import TelaRevisao
from .tela_sapl import TelaSAPL


class Aplicacao(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SAPL Parnamirim — Indicações")
        self.geometry("1200x880")
        self.minsize(1000, 680)
        visual.aplicar_estilos(self)

        # Primeira execucao do .exe: cria input/, output/ e traz os arquivos
        # de configuracao para o lado do programa. Sem isto, o programa abriria
        # e falharia no primeiro clique por falta de sapl_ids.json.
        from src.config import preparar_pasta_de_trabalho

        preparar_pasta_de_trabalho()

        self.estado = Estado.carregar()

        visual.cabecalho(
            self, "Indicações — Câmara Municipal de Parnamirim",
            "Separa o lote, lê cada indicação e prepara o cadastro no SAPL.",
        ).pack(fill="x")

        self.abas = ttk.Notebook(self)
        self.abas.pack(fill="both", expand=True, padx=16, pady=16)

        self.tela_inicio = TelaInicio(self.abas, self)
        self.tela_revisao = TelaRevisao(self.abas, self)
        self.tela_sapl = TelaSAPL(self.abas, self)
        self.tela_ambiente = TelaAmbiente(self.abas, self)

        self.abas.add(self.tela_inicio, text="1. Processar")
        self.abas.add(self.tela_revisao, text="2. Conferir")
        self.abas.add(self.tela_sapl, text="3. Enviar ao SAPL")
        self.abas.add(self.tela_ambiente, text="Instalação")
        self.abas.bind("<<NotebookTabChanged>>", self._ao_trocar_aba)

        self.atualizar_abas()
        self.protocol("WM_DELETE_WINDOW", self.ao_fechar)

        # A conferencia da instalacao roda depois que a janela ja apareceu:
        # ela consulta o Tesseract e o Ollama, e esperar por isso antes de
        # desenhar deixaria a impressao de que o programa nao abriu.
        self.after(150, self.tela_ambiente.verificar)

    # ------------------------------------------------------------- navegacao
    def _ao_trocar_aba(self, evento=None) -> None:
        atual = self.abas.select()
        if atual == str(self.tela_inicio):
            self.tela_inicio.atualizar_lista()
        elif atual == str(self.tela_sapl):
            self.tela_sapl.recarregar()

    def ir_para_revisao(self) -> None:
        self.abas.select(self.tela_revisao)

    def atualizar_abas(self) -> None:
        """Poe entre parenteses quanto falta em cada etapa."""
        pendentes = self.tela_revisao.pendentes()
        prontas = len(self.tela_sapl.prontas)
        self.abas.tab(self.tela_revisao,
                      text=f"2. Conferir ({pendentes})" if pendentes else "2. Conferir")
        self.abas.tab(self.tela_sapl,
                      text=f"3. Enviar ao SAPL ({prontas})" if prontas
                      else "3. Enviar ao SAPL")
        # A aba de instalacao so chama atencao quando falta algo obrigatorio.
        falta = any(not p.ok and p.obrigatoria
                    for p in getattr(self.tela_ambiente, "pecas", []))
        self.abas.tab(self.tela_ambiente,
                      text="Instalação (!)" if falta else "Instalação")

    def ir_para_instalacao(self) -> None:
        self.abas.select(self.tela_ambiente)

    def recarregar(self, indicacoes=None) -> None:
        """Depois de uma extracao: as outras telas releem o que saiu."""
        self.tela_revisao.recarregar()
        self.tela_sapl.recarregar()
        self.atualizar_abas()

    def processar_de_novo(self) -> None:
        self.abas.select(self.tela_inicio)
        self.tela_inicio.fazer_tudo()

    # --------------------------------------------------------------- apoio
    def abrir_no_explorador(self, caminho: Path) -> None:
        """Abre a pasta (ou seleciona o arquivo) no gerenciador do sistema."""
        try:
            if sys.platform == "win32":
                if caminho.is_dir():
                    os.startfile(caminho)  # noqa: S606 - caminho e do proprio programa
                else:
                    subprocess.run(["explorer", "/select,", str(caminho)], check=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(caminho)], check=False)
            else:
                subprocess.run(["xdg-open", str(caminho)], check=False)
        except OSError as e:
            messagebox.showerror("Não deu para abrir", f"{caminho}\n\n{e}")

    def ao_fechar(self) -> None:
        rodando = self.tela_inicio.tarefa is not None and self.tela_inicio.tarefa.rodando()
        sessao = self.tela_sapl.sessao
        navegador = sessao is not None and sessao.is_alive()
        if rodando or navegador:
            o_que = "O processamento" if rodando else "A sessão do SAPL"
            if not messagebox.askyesno(
                "Ainda está rodando",
                f"{o_que} ainda não terminou. Fechar agora interrompe.\n\n"
                "Fechar mesmo assim?",
            ):
                return
            if navegador:
                sessao.parar()
        self.estado.salvar()
        self.destroy()


def main() -> int:
    app = Aplicacao()
    app.mainloop()
    return 0
