"""Gera o programa distribuivel SEM empacotar num .exe.

    .venv\\Scripts\\python scripts\\gerar_pacote.py

Sai em dist/SAPL Parnamirim/, pronta para compactar. Quem recebe descompacta e
clica em "SAPL Parnamirim.bat" - sem instalar Python, sem .venv, sem prompt.

POR QUE ASSIM, E NAO UM .EXE
----------------------------
O executavel gerado por PyInstaller (scripts\\gerar_exe.py) foi BLOQUEADO pelo
Windows Defender nas maquinas da Camara. Nao por estar errado: binario novo,
sem assinatura digital e que descompacta codigo na memoria tem exatamente o
formato de um programa malicioso empacotado. Falta reputacao, nao seguranca.

Aqui nao existe binario novo nenhum. O programa roda no python.exe OFICIAL,
baixado do python.org e ASSINADO pela Python Software Foundation - um
executavel que o Windows ja conhece e em que ja confia. O que a pasta carrega
alem dele sao arquivos .py, que nao disparam heuristica de empacotador.

Custa duas coisas: a pasta fica maior e mais "bagunçada" que um .exe unico, e
o codigo vai legivel (o que, para software de orgao publico, nao e defeito).

O TKINTER PRECISA SER TRAZIDO A MAO
-----------------------------------
O pacote "embeddable" do python.org nao inclui o Tkinter - e a interface
inteira depende dele. Entao os arquivos sao copiados da instalacao local do
Python (mesma versao 3.13, mesma ABI): _tkinter.pyd, as DLLs do Tcl/Tk e a
pasta tcl/ com os scripts que o Tk carrega em tempo de execucao.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
NOME = "SAPL Parnamirim"
DESTINO = RAIZ / "dist" / NOME
PYTHON_DIR = DESTINO / "python"

# Mesma serie 3.13 da instalacao local: o _tkinter.pyd copiado de la so
# funciona no interpretador da mesma versao (ABI cp313).
VERSAO = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
URL_EMBED = f"https://www.python.org/ftp/python/{VERSAO}/python-{VERSAO}-embed-amd64.zip"
URL_PIP = "https://bootstrap.pypa.io/get-pip.py"

# O que precisa vir junto do codigo. O resto (dist/, build/, .venv/, tests/)
# nao vai: e ferramenta de quem desenvolve.
PASTAS_DO_PROGRAMA = ["src", "gui", "scripts", "config"]


def _ambiente_isolado() -> dict:
    """Ambiente sem nenhum vestigio do Python da maquina de quem gera.

    BUG REAL, e dos silenciosos: a instalacao do Python pela Microsoft Store
    deixa PYTHONUSERBASE apontando para as bibliotecas do usuario. O Python
    embutido, com "import site" ligado, enxergava aquela pasta - e o efeito
    foi duplo:

      - o pip achou que Pillow e requests "ja estavam instalados" e nao os
        colocou no pacote;
      - a conferencia importou os dois com sucesso... da maquina de quem
        gerou, nao do pacote.

    Ou seja: o pacote saia quebrado e o teste dizia que estava bom. So
    falharia na mao do usuario. Tirar essas variaveis e o que garante que
    tudo que o programa precisa esta DENTRO da pasta.
    """
    ambiente = {k: v for k, v in os.environ.items()
                if not k.upper().startswith("PYTHON")}
    ambiente["PYTHONNOUSERSITE"] = "1"
    return ambiente


def baixar(url: str, destino: Path) -> None:
    print(f"  baixando {url.rsplit('/', 1)[-1]} ...")
    with urllib.request.urlopen(url, timeout=180) as resposta:
        destino.write_bytes(resposta.read())


def montar_python() -> None:
    """Python oficial embutido + Tkinter trazido da instalacao local."""
    PYTHON_DIR.mkdir(parents=True, exist_ok=True)
    zip_embed = DESTINO / "_python.zip"
    baixar(URL_EMBED, zip_embed)
    with zipfile.ZipFile(zip_embed) as z:
        z.extractall(PYTHON_DIR)
    zip_embed.unlink()

    # O ._pth do pacote embeddable tranca o sys.path. Sem liberar, nem as
    # bibliotecas instaladas nem o codigo do programa sao encontrados.
    for pth in PYTHON_DIR.glob("python*._pth"):
        linhas = pth.read_text(encoding="utf-8").splitlines()
        linhas = [l for l in linhas if l.strip() != "#import site"]
        pth.write_text(
            "\n".join(linhas + ["Lib", "Lib\\site-packages", "..", "import site"]),
            encoding="utf-8",
        )

    print("  trazendo o Tkinter da instalacao local ...")
    base = Path(sys.base_prefix)
    lib = PYTHON_DIR / "Lib"
    lib.mkdir(exist_ok=True)
    shutil.copytree(base / "Lib" / "tkinter", lib / "tkinter", dirs_exist_ok=True)
    for nome in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll"):
        origem = base / "DLLs" / nome
        if origem.is_file():
            shutil.copy2(origem, PYTHON_DIR / nome)
    # Os scripts do proprio Tcl/Tk, carregados quando a janela abre.
    shutil.copytree(base / "tcl", PYTHON_DIR / "tcl", dirs_exist_ok=True)


# Tudo que o programa importa em algum momento. E por esta lista que o pacote
# e conferido no fim - nao pelo codigo de saida do pip.
MODULOS_NECESSARIOS = [
    "tkinter", "PIL", "PIL.ImageTk", "pypdf", "pypdfium2", "pdfplumber",
    "rapidfuzz", "unidecode", "requests", "playwright", "pytesseract",
]


def instalar_bibliotecas() -> None:
    python = PYTHON_DIR / "python.exe"
    get_pip = DESTINO / "get-pip.py"
    baixar(URL_PIP, get_pip)
    print("  instalando o pip ...")
    subprocess.run([str(python), str(get_pip), "--no-warn-script-location", "-q"],
                   check=True, cwd=DESTINO, env=_ambiente_isolado())
    get_pip.unlink()

    print("  instalando as bibliotecas do requirements.txt ...")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-warn-script-location",
         "-r", str(RAIZ / "requirements.txt")],
        check=True, cwd=DESTINO, env=_ambiente_isolado(),
    )


def conferir_pacote() -> list[str]:
    """Importa de verdade cada biblioteca dentro do Python embutido.

    Existe porque o "pip install" ja terminou com codigo de sucesso deixando
    Pillow e requests de fora - e o pacote so falharia na mao do usuario, ao
    abrir a primeira imagem. Conferir por importacao e a unica prova de que a
    pasta esta completa.
    """
    python = PYTHON_DIR / "python.exe"
    faltando = []
    for modulo in MODULOS_NECESSARIOS:
        resultado = subprocess.run(
            [str(python), "-c", f"import {modulo}"],
            cwd=DESTINO, capture_output=True, text=True,
            env=_ambiente_isolado(),
        )
        if resultado.returncode != 0:
            faltando.append(modulo)
    return faltando


def instalar_faltantes(faltando: list[str]) -> None:
    """Segunda tentativa, so do que faltou."""
    # Nome do modulo -> nome do pacote no pip, quando diferem.
    pacote_de = {"PIL": "Pillow", "PIL.ImageTk": "Pillow", "unidecode": "Unidecode"}
    pacotes = sorted({pacote_de.get(m, m) for m in faltando if m != "tkinter"})
    if not pacotes:
        return
    print(f"  faltou: {', '.join(pacotes)} - instalando de novo ...")
    subprocess.run(
        [str(PYTHON_DIR / "python.exe"), "-m", "pip", "install",
         "--no-warn-script-location", *pacotes],
        cwd=DESTINO, check=False, env=_ambiente_isolado(),
    )


def copiar_programa() -> None:
    for pasta in PASTAS_DO_PROGRAMA:
        shutil.copytree(
            RAIZ / pasta, DESTINO / pasta,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "interface.json"),
        )
    (DESTINO / "input").mkdir(exist_ok=True)
    (DESTINO / "LEIA-ME.txt").write_text(LEIAME, encoding="utf-8")
    (DESTINO / f"{NOME}.bat").write_text(ATALHO, encoding="utf-8")


def main() -> int:
    if DESTINO.exists():
        print(f"limpando {DESTINO} ...")
        shutil.rmtree(DESTINO)
    DESTINO.mkdir(parents=True)

    print(f"Montando o programa com Python {VERSAO} embutido ...\n")
    try:
        montar_python()
        instalar_bibliotecas()
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"\nFalhou: {e}")
        print("Confira a conexao com a internet e tente de novo.")
        return 1
    copiar_programa()

    print("\nConferindo o pacote ...")
    faltando = conferir_pacote()
    if faltando:
        instalar_faltantes(faltando)
        faltando = conferir_pacote()
    if faltando:
        print(f"\nO pacote esta INCOMPLETO - nao importa: {', '.join(faltando)}")
        print("Nao distribua assim: rode de novo, ou instale a mao com")
        print(f"  \"{PYTHON_DIR / 'python.exe'}\" -m pip install <pacote>")
        return 1
    print("  todas as bibliotecas importam dentro do pacote")

    tamanho = sum(f.stat().st_size for f in DESTINO.rglob("*") if f.is_file())
    print(f"\nPronto: {DESTINO}")
    print(f"Tamanho: {tamanho / 1024 / 1024:.0f} MB")
    print("\nCompacte a pasta inteira em um .zip para distribuir.")
    print(f"Quem receber descompacta e clica em \"{NOME}.bat\".")
    return 0


# pythonw.exe (sem console) evita a janela preta. O erro de abertura vira
# janela de aviso e vai para output\erro_interface.txt - ver scripts\interface.py.
ATALHO = """\
@echo off
cd /d "%~dp0"
rem Isola do Python que a maquina por acaso tenha instalado: sem isto, uma
rem biblioteca do usuario (pasta PYTHONUSERBASE) entra na frente da que vem
rem no pacote, e o programa passa a depender do computador em que roda.
set PYTHONNOUSERSITE=1
set PYTHONPATH=
set PYTHONHOME=
start "" "python\\pythonw.exe" "scripts\\interface.py"
"""

LEIAME = """\
INDICAÇÕES - CÂMARA MUNICIPAL DE PARNAMIRIM
===========================================

COMO USAR
---------
1. Clique duas vezes em "SAPL Parnamirim.bat".
2. Na primeira aba, adicione os PDFs com as indicações, informe o ano e
   clique em FAZER TUDO.
3. Na segunda aba, confira as indicações que o programa não conseguiu ler
   sozinho. A página escaneada aparece do lado dos campos. A data está no
   carimbo "Lido na Sessão", escrita à mão no verso: use o botão
   "Ir ao carimbo" para vê-la e digite no campo Data.
4. Na terceira aba, envie para o SAPL. O programa preenche tudo - inclusive
   a data e o PDF anexado - e para. Você confere e clica em salvar no SAPL.

PRIMEIRA VEZ NESTE COMPUTADOR
-----------------------------
A terceira aba precisa de um navegador próprio, com cerca de 90 MB, baixado
uma única vez. Abra a aba "Instalação" e clique em "Preparar o que falta".
Precisa de internet só para isso. As duas primeiras abas funcionam sem
nenhum download.

ONDE FICAM OS ARQUIVOS
----------------------
Tudo nesta mesma pasta:

  input/    os PDFs que você vai processar
  output/   os PDFs separados, um por indicação
  config/   suas correções e os nomes de vereadores que você confirmou

A pasta config/ é o seu trabalho acumulado. Ao atualizar o programa, copie
essa pasta para a versão nova - as correções já feitas continuam valendo.

A pasta python/ é o Python oficial (python.org), assinado pela Python
Software Foundation. Não apague nem mova.

NÃO FUNCIONOU?
--------------
Se o programa não abrir, veja o arquivo output/erro_interface.txt.
"""


if __name__ == "__main__":
    raise SystemExit(main())
