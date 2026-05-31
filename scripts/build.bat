@echo off
REM Build: create the Python venv, install backend deps, install + build the web UI.
setlocal
cd /d "%~dp0..\source_code" || exit /b 1

if not exist ".venv\pyvenv.cfg" (
  echo [build] Creating virtual environment...
  if exist ".venv" rmdir /s /q ".venv"
  python -m venv --upgrade-deps .venv || (echo [build] Failed to create venv & exit /b 1)
  if not exist ".venv\Scripts\pip.exe" (
    echo [build] Bootstrapping pip...
    ".venv\Scripts\python.exe" -m ensurepip --upgrade || (echo [build] Failed to bootstrap pip & exit /b 1)
  )
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
