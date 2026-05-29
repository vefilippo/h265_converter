@echo off
setlocal

cd /d "%~dp0"

set "VENV_DIR=.venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [ERRORE] Virtualenv non trovata. Esegui prima setup_venv.bat
  exit /b 1
)

REM Esegui il comando usando il Python della venv (senza activate)
"%VENV_DIR%\Scripts\python.exe" -m transcoder.cli all new

endlocal
