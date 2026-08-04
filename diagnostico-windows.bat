@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ThermoPower Monitor - Diagnostico

echo === ThermoPower Monitor - diagnostico ===
echo Diretorio: %CD%
echo Data: %DATE% %TIME%
echo.

echo --- Ferramentas ---
where python 2>nul
python --version 2>&1
where npm 2>nul
npm --version 2>&1
where node 2>nul
node --version 2>&1
echo.

echo --- Estrutura ---
if exist ".venv\Scripts\python.exe" (echo [OK] Ambiente Python) else (echo [FALHA] Ambiente Python ausente)
if exist "frontend\node_modules" (echo [OK] node_modules) else (echo [FALHA] node_modules ausente)
if exist "backend\alembic.ini" (echo [OK] Alembic) else (echo [FALHA] alembic.ini ausente)
echo.

echo --- Portas seriais detectadas ---
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "from serial.tools import list_ports; p=list(list_ports.comports()); print('\n'.join(f'{x.device} - {x.description}' for x in p) if p else 'Nenhuma porta serial detectada')"
) else (
  echo Ambiente Python indisponivel para listar portas.
)
echo.

echo --- Portas de rede ---
netstat -ano | findstr ":8000 :5173"
echo.

echo --- Banco e imports ---
if exist ".venv\Scripts\python.exe" (
  pushd backend
  "..\.venv\Scripts\python.exe" -m alembic current 2>&1
  "..\.venv\Scripts\python.exe" -c "from app.importers import At4532XlsxImporter,Gpm8213TxtImporter; print('Importadores: OK')" 2>&1
  popd
)
echo.
echo Copie toda esta saida ao solicitar suporte.
pause
endlocal
