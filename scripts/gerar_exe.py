"""Gera o programa distribuivel: uma pasta com o .exe dentro.

    .venv\\Scripts\\python scripts\\gerar_exe.py

Sai em dist/SAPL-Parnamirim/, pronta para compactar e mandar para quem vai
usar. Quem recebe descompacta e clica em "SAPL Parnamirim.exe" - sem Python,
sem .venv, sem prompt de comando.

Por que "onedir" e nao um .exe unico: o arquivo unico descompacta tudo numa
pasta temporaria a cada abertura, o que deixa a partida lenta (dezenas de
segundos com o pypdfium2 e o Playwright dentro) e costuma acordar o antivirus.
A pasta abre rapido e e o formato que o proprio PyInstaller recomenda para
aplicacao com muita biblioteca binaria.

O navegador do Playwright (~90 MB) NAO vai no pacote: ele e baixado na
primeira execucao, pela aba "Instalação". Isso mantem o zip em torno de 100 MB
em vez de 200 MB, e quem so vai processar e conferir nem precisa dele.

ANTIVIRUS
---------
Executavel gerado por PyInstaller, sem assinatura digital, e alvo classico de
FALSO POSITIVO: o Windows Defender pode bloquear a execucao simplesmente por
ser um binario novo, desconhecido e que descompacta codigo na memoria - o
mesmo padrao usado por programa malicioso empacotado. Nao ha nada de errado
com o programa; o que falta e reputacao.

O "--noupx" acima evita a compressao UPX, que e o gatilho mais comum desse
tipo de deteccao. Resolver de vez exige uma destas saidas, na ordem em que
funcionam melhor (ver a secao "Antivírus" no README):

  1. assinar o executavel com certificado de codigo
  2. submeter o arquivo a Microsoft como falso positivo
  3. o TI do orgao liberar o programa na politica do Defender
  4. distribuir sem empacotar: Python embutido + atalho, sem gerar .exe
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
NOME = "SAPL Parnamirim"
DESTINO = RAIZ / "dist" / NOME


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Falta o PyInstaller (so para gerar o executavel, nao para usar):")
        print("  .venv\\Scripts\\python -m pip install pyinstaller")
        return 1

    comando = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",                 # sem janela preta de console
        "--noupx",                    # ver "Antivirus" no README
        "--name", NOME,
        # Os modelos de configuracao viajam dentro do pacote; na primeira
        # execucao sao copiados para o lado do .exe (ver config.preparar_
        # pasta_de_trabalho), onde podem ser editados e crescer com o uso.
        "--add-data", f"{RAIZ / 'config'}{__import__('os').pathsep}config",
        # O Playwright traz um driver em node que o PyInstaller nao acha
        # sozinho - sem isto, a aba de envio ao SAPL abre e nao funciona.
        "--collect-all", "playwright",
        # Tkinter+Pillow: o ImageTk fica escondido atras de import dinamico.
        "--hidden-import", "PIL._tkinter_finder",
        # Peso morto: sao dependencias opcionais de outras bibliotecas, nada
        # aqui usa. Cortam bem mais de 100 MB do pacote final.
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "matplotlib",
        "--exclude-module", "scipy",
        "--exclude-module", "PyQt5",
        "--exclude-module", "PySide6",
        "--exclude-module", "IPython",
        "--exclude-module", "pytest",
        str(RAIZ / "scripts" / "interface.py"),
    ]

    print("Gerando o executavel (leva alguns minutos) ...\n")
    resultado = subprocess.run(comando, cwd=RAIZ)
    if resultado.returncode != 0:
        print("\nA geracao falhou - veja o erro do PyInstaller acima.")
        return resultado.returncode

    if not DESTINO.exists():
        print(f"\nO PyInstaller terminou mas {DESTINO} nao apareceu.")
        return 1

    # input/ vazia e um LEIAME curto: a pessoa abre a pasta e entende o que
    # fazer sem ler documentacao nenhuma.
    (DESTINO / "input").mkdir(exist_ok=True)
    (DESTINO / "LEIA-ME.txt").write_text(LEIAME, encoding="utf-8")

    tamanho = sum(f.stat().st_size for f in DESTINO.rglob("*") if f.is_file())
    print(f"\nPronto: {DESTINO}")
    print(f"Tamanho: {tamanho / 1024 / 1024:.0f} MB")
    print("\nPara distribuir, compacte a pasta inteira em um .zip.")
    print("Quem receber descompacta e clica em "
          f"\"{NOME}.exe\" - nao precisa instalar mais nada.")
    return 0


LEIAME = """\
INDICAÇÕES - CÂMARA MUNICIPAL DE PARNAMIRIM
===========================================

COMO USAR
---------
1. Clique duas vezes em "SAPL Parnamirim.exe".
2. Na primeira aba, adicione os PDFs com as indicações, informe o ano e a
   data de apresentação, e clique em FAZER TUDO.
3. Na segunda aba, confira as indicações que o programa não conseguiu ler
   sozinho. A página escaneada aparece do lado dos campos.
4. Na terceira aba, envie para o SAPL, uma por vez.

PRIMEIRA VEZ NESTE COMPUTADOR
-----------------------------
A terceira aba (enviar ao SAPL) precisa de um navegador próprio, que tem
cerca de 90 MB e é baixado uma única vez. Abra a aba "Instalação" e clique
em "Preparar o que falta". Precisa de internet só para isso.

As duas primeiras abas funcionam sem nenhum download.

ONDE FICAM OS ARQUIVOS
----------------------
Tudo do lado do programa, nesta mesma pasta:

  input/    os PDFs que você vai processar
  output/   os PDFs separados, um por indicação, prontos para anexar
  config/   suas correções e os nomes de vereadores que você confirmou

A pasta config/ é o seu trabalho acumulado. Ao atualizar o programa, copie
essa pasta para a versão nova - as correções que você já fez continuam
valendo e não precisam ser refeitas.

NÃO FUNCIONOU?
--------------
Se o programa não abrir, veja o arquivo output/erro_interface.txt.

Se o Windows disser que bloqueou o programa: isso é um alarme falso comum
com programas novos que ainda não têm histórico de uso. NÃO desligue o
antivírus. Fale com o setor de TI - eles liberam o programa na política do
Defender, como fazem com qualquer sistema interno.
"""


if __name__ == "__main__":
    raise SystemExit(main())
