# Prepara o projeto em outro PC (Windows). Rode de dentro da pasta do projeto:
#
#     powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
#
# Nada aqui depende da maquina onde o projeto foi escrito: o que e local (venv,
# navegador do Playwright, modelo do Ollama) e recriado do zero.

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
Write-Host "Projeto em: $raiz`n"

# $ErrorActionPreference NAO interrompe quando um .exe retorna erro - ele so
# vale para cmdlets. Sem checar $LASTEXITCODE, um pip que falha passa batido e
# o script termina dizendo "Pronto" com o ambiente quebrado.
function Confirmar($oque) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nFALHOU: $oque (codigo $LASTEXITCODE)" -ForegroundColor Red
        Write-Host "Corrija o erro acima e rode o instalador de novo."
        exit 1
    }
}

# --- 0. Caminho curto o bastante ------------------------------------------
# O Windows limita caminhos a 260 caracteres por padrao, e algumas bibliotecas
# (pypdfium2) criam arquivos bem fundo dentro do .venv.
if ($raiz.Length -gt 90) {
    Write-Host "O caminho do projeto tem $($raiz.Length) caracteres:" -ForegroundColor Red
    Write-Host "  $raiz"
    Write-Host "`nIsso estoura o limite de 260 caracteres do Windows ao instalar as"
    Write-Host "bibliotecas. Mova o projeto para um caminho curto, por exemplo:"
    Write-Host "  C:\SAPL-Parnamirim"
    exit 1
}

# --- 1. Python -------------------------------------------------------------
$python = $null
foreach ($tentativa in @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
)) {
    if (Test-Path $tentativa) { $python = $tentativa; break }
}
if (-not $python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    # O atalho da Microsoft Store se chama python.exe mas nao e o Python.
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { $python = $cmd.Source }
}
if (-not $python) {
    Write-Host "Python nao encontrado. Instalando 3.12 via winget..." -ForegroundColor Yellow
    winget install --id Python.Python.3.12 -e --source winget --scope user `
        --accept-source-agreements --accept-package-agreements --disable-interactivity
    $python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $python)) {
        Write-Host "`nFALHOU: winget nao instalou o Python em $python" -ForegroundColor Red
        Write-Host "Instale manualmente de https://www.python.org/downloads/ e rode de novo."
        exit 1
    }
}
Write-Host "Python: $python"
& $python --version
Confirmar "executar o Python"

# --- 2. Ambiente virtual e bibliotecas ------------------------------------
# O .venv NAO e copiavel entre PCs: guarda caminhos absolutos. Sempre recriar.
if (Test-Path "$raiz\.venv") {
    Write-Host "`n.venv existente removido (guarda caminhos da outra maquina)."
    Remove-Item "$raiz\.venv" -Recurse -Force
}
Write-Host "`nCriando .venv e instalando as bibliotecas..."
& $python -m venv "$raiz\.venv"
Confirmar "criar o .venv"

$vpy = "$raiz\.venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet
Confirmar "atualizar o pip"
& $vpy -m pip install -r "$raiz\requirements.txt" --quiet
Confirmar "instalar as bibliotecas do requirements.txt"
Write-Host "Bibliotecas instaladas."

# --- 3. Navegador do Playwright -------------------------------------------
# Necessario apenas para o passo 02 (preencher o SAPL). ~190 MB.
Write-Host "`nBaixando o Chromium do Playwright (so o passo 02 usa)..."
& $vpy -m playwright install chromium
Confirmar "instalar o Chromium do Playwright"

# --- 4. Ollama (OPCIONAL) -------------------------------------------------
# Sem ele, use --sem-ollama: o conjunto de indicacoes prontas e identico.
$ollama = $null
foreach ($t in @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
                 "$env:ProgramFiles\Ollama\ollama.exe")) {
    if (Test-Path $t) { $ollama = $t; break }
}
if (-not $ollama) { $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source }

if ($ollama) {
    Write-Host "`nOllama: $ollama"
    # 'ollama list' devolve VARIAS linhas. Comparar o array com -notmatch
    # retorna as linhas que nao casam (o cabecalho), o que e sempre verdadeiro
    # e fazia o modelo ser rebaixado a cada execucao. Juntar antes resolve.
    $modelos = (& $ollama list 2>$null) -join "`n"
    if ($modelos -like "*qwen2.5:3b-instruct*") {
        Write-Host "Modelo qwen2.5:3b-instruct ja presente."
    } else {
        Write-Host "Baixando qwen2.5:3b-instruct (~1,9 GB)..."
        & $ollama pull qwen2.5:3b-instruct
        Confirmar "baixar o modelo do Ollama"
    }
} else {
    Write-Host "`nOllama nao instalado - OPCIONAL." -ForegroundColor Yellow
    Write-Host "  Sem ele, rode o pipeline com --sem-ollama (mesmo resultado;"
    Write-Host "  o que se perde e so a coluna de sugestao do glossario)."
    Write-Host "  Para instalar depois: winget install Ollama.Ollama"
}

# --- 5. Verificacao -------------------------------------------------------
Write-Host "`nVerificando..."
& $vpy -c "import pypdf, pdfplumber, pypdfium2, PIL, rapidfuzz, requests, playwright; print('  bibliotecas ok')"
Confirmar "importar as bibliotecas"
& $vpy -m compileall -q "$raiz\src" "$raiz\scripts"
Confirmar "compilar o codigo"
Write-Host "  codigo compila ok"

Write-Host "`nPronto. Para usar:" -ForegroundColor Green
Write-Host '  .venv\Scripts\python scripts\00_diagnostico.py "CAMINHO\DO.pdf" 2023'
Write-Host '  .venv\Scripts\python scripts\01_extrair.py    "CAMINHO\DO.pdf"'
Write-Host '  .venv\Scripts\python scripts\02_preencher_sapl.py'
