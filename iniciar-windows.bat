@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ThermoPower Monitor - Inicializador

where python >nul 2>nul || (
  echo [ERRO] Python nao encontrado no PATH.
  echo Instale Python 3.12 ou superior e execute diagnostico-windows.bat.
  pause & exit /b 1
)
where npm >nul 2>nul || (
  echo [ERRO] Node.js/npm nao encontrado no PATH.
  echo Instale Node.js LTS e execute diagnostico-windows.bat.
  pause & exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/5] Criando ambiente Python...
  python -m venv .venv || (pause & exit /b 1)
)

echo [2/5] Verificando dependencias do backend...
".venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt || (
  echo [ERRO] Nao foi possivel instalar as dependencias Python.
  pause & exit /b 1
)

if not exist "frontend\node_modules" (
  echo [3/5] Instalando dependencias do frontend...
  pushd frontend
  call npm install || (popd & pause & exit /b 1)
  popd
) else (
  echo [3/5] Dependencias do frontend encontradas.
)

echo [4/5] Aplicando migracoes do banco...
pushd backend
"..\.venv\Scripts\python.exe" -m alembic upgrade head || (
  popd
  echo [ERRO] Falha na migracao. Execute diagnostico-windows.bat.
  pause & exit /b 1
)
popd

echo [5/5] Iniciando servicos...
for /f "usebackq tokens=1,* delims==" %%A in (`powershell -NoProfile -Command "$c = Get-Content -Raw 'release-config.json' ^| ConvertFrom-Json; 'THERMOPOWER_DEMO_ADMIN_EMAIL=' + $c.homologation.email; 'THERMOPOWER_DEMO_ADMIN_PASSWORD=' + $c.homologation.password"`) do set "%%A=%%B"
set "THERMOPOWER_LOGIN_PREFILL_ENABLED=1"
start "ThermoPower Backend" cmd /k "cd /d ""%~dp0backend"" && ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "ThermoPower Frontend" cmd /k "cd /d ""%~dp0frontend"" && npm run dev -- --host 127.0.0.1"

timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:5173"
echo.
echo ThermoPower aberto. As credenciais de homologacao sao preenchidas pela interface.
echo Mantenha as duas janelas de servico abertas.
endlocal
