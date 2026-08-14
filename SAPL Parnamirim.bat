@echo off
rem Atalho para abrir a interface com dois cliques, sem digitar nada.
rem Usa pythonw.exe (sem janela preta). Erros de abertura viram uma janela de
rem aviso e ficam gravados em output\erro_interface.txt - ver scripts\interface.py.
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo.
  echo   O ambiente ainda nao foi preparado nesta maquina.
  echo.
  echo   Rode uma vez, nesta mesma pasta:
  echo     powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
  echo.
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "scripts\interface.py"
