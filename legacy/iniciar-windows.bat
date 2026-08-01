@echo off
title ThermoPower Monitor
cd /d "%~dp0"
echo.
echo Iniciando o ThermoPower Monitor...
echo Endereco: http://localhost:8000
echo.
start "" http://localhost:8000
py -m http.server 8000
if errorlevel 1 (
  echo.
  echo O comando "py" nao funcionou. Tentando "python"...
  python -m http.server 8000
)
pause
