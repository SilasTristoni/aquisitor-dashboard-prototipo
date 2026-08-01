@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Ambiente Python nao encontrado.
  echo Execute: python -m venv .venv
  echo Depois:  .venv\Scripts\python -m pip install -r backend\requirements.txt
  pause
  exit /b 1
)

if not exist "frontend\node_modules" (
  echo Dependencias do frontend nao encontradas.
  echo Execute: cd frontend ^&^& npm install
  pause
  exit /b 1
)

echo Iniciando o backend em http://127.0.0.1:8000 ...
start "ThermoPower Backend" cmd /k "cd /d ""%~dp0backend"" && ..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo Iniciando o frontend em http://127.0.0.1:5173 ...
start "ThermoPower Frontend" cmd /k "cd /d ""%~dp0frontend"" && npm run dev"

timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:5173"
echo.
echo Duas janelas foram abertas. Mantenha ambas abertas durante o teste.
echo Para encerrar, pressione Ctrl+C em cada uma.
endlocal
