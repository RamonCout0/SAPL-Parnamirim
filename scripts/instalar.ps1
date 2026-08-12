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
# Necessario apenas para o passo 02 (preencher o SAPL). Firefox, nao Chromium:
# e a instancia que a tela de preenchimento usa (propria do Playwright, com
# perfil salvo em .perfil_navegador/ - nao e o Firefox do dia a dia do
# usuario). ~120 MB.
Write-Host "`nBaixando o Firefox do Playwright (so o passo 02 usa)..."
& $vpy -m playwright install firefox
Confirmar "instalar o Firefox do Playwright"

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

# --- 5. Tesseract OCR (OPCIONAL) -------------------------------------------
# So entra em acao para paginas escaneadas SEM camada de texto nenhuma (raro -
# a maioria dos lotes ja vem com OCR embutido). Sem o Tesseract, essas
# paginas raras simplesmente vao para revisao manual em vez de serem lidas -
# mais lento para voce, mas nao quebra nada.
$tesseract = (Get-Command tesseract -ErrorAction SilentlyContinue).Source
foreach ($t in @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
                 "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe")) {
    if (-not $tesseract -and (Test-Path $t)) { $tesseract = $t }
}

if (-not $tesseract) {
    Write-Host "`nInstalando Tesseract OCR (opcional, ~80 MB)..." -ForegroundColor Yellow
    winget install --id UB-Mannheim.TesseractOCR -e --source winget `
        --accept-source-agreements --accept-package-agreements --disable-interactivity
    $codigo = $LASTEXITCODE

    # O codigo de saida do winget NAO e confiavel aqui: se o pacote ja estava
    # registrado no winget mas nosso Get-Command/caminhos de cima nao acharam
    # o executavel (PATH desatualizado na sessao, por exemplo), o winget
    # tenta "atualizar" em vez de instalar, nao acha versao mais nova e
    # devolve erro - mesmo com o Tesseract funcionando perfeitamente no
    # disco (reproduzido durante o desenvolvimento: winget devolveu erro
    # 0x8a15002b "nenhuma atualizacao disponivel" com o programa ja
    # instalado e funcional). Por isso sempre reconfere o arquivo, em vez de
    # confiar so no codigo de saida.
    foreach ($t in @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
                     "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe")) {
        if (-not $tesseract -and (Test-Path $t)) { $tesseract = $t }
    }
    if (-not $tesseract) {
        Write-Host "  nao instalou automaticamente (codigo $codigo) - sem problema, e opcional." -ForegroundColor Yellow
        Write-Host "  Para instalar depois: winget install UB-Mannheim.TesseractOCR"
    }
}

if ($tesseract) {
    Write-Host "Tesseract: $tesseract"
    $tessdata = "$raiz\tessdata"
    New-Item -ItemType Directory -Force $tessdata | Out-Null
    $por = "$tessdata\por.traineddata"
    if (-not (Test-Path $por)) {
        Write-Host "Baixando pacote de portugues (~2 MB)..."
        try {
            Invoke-WebRequest -UseBasicParsing `
                -Uri "https://github.com/tesseract-ocr/tessdata_fast/raw/main/por.traineddata" `
                -OutFile $por
            Write-Host "  pacote de portugues pronto."
        } catch {
            Write-Host "  FALHOU ao baixar o pacote de portugues: $_" -ForegroundColor Yellow
            Write-Host "  Baixe manualmente em https://github.com/tesseract-ocr/tessdata_fast"
            Write-Host "  e salve em $por"
        }
    } else {
        Write-Host "Pacote de portugues ja presente."
    }
}

# --- 6. Verificacao -------------------------------------------------------
Write-Host "`nVerificando..."
& $vpy -c "import pypdf, pdfplumber, pypdfium2, PIL, rapidfuzz, requests, playwright; print('  bibliotecas ok')"
Confirmar "importar as bibliotecas"
& $vpy -m compileall -q "$raiz\src" "$raiz\scripts"
Confirmar "compilar o codigo"
Write-Host "  codigo compila ok"

Write-Host "`nPronto. Para usar:" -ForegroundColor Green
Write-Host '  1. Coloque os PDFs em input\'
Write-Host '  2. .venv\Scripts\python scripts\01_extrair.py'
Write-Host '  3. .venv\Scripts\python scripts\03_revisar.py       (se houver pendencias)'
Write-Host '  4. .venv\Scripts\python scripts\02_preencher_sapl.py'
