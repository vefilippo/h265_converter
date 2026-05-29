@echo off
REM Build: create the Python venv, install backend deps, install + build the web UI.
setlocal
cd /d "%~dp0..\source_code" || exit /b 1

if not exist ".venv\Scripts\python.exe" (
  echo [build] Creating virtual environment...
  python -m venv .venv || (echo [build] Failed to create venv & exit /b 1)
)

echo [build] Installing Python dependencies...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1

echo [build] Installing and building the web UI...
pushd web
call npm install || (popd & exit /b 1)
call npm run build || (popd & exit /b 1)
popd

echo.
echo [build] Done. Copy source_code\.env.example to source_code\.env and fill it in,
echo         then run scripts\run.bat to start the service.
endlocal
