@echo off
setlocal

REM Vai nella cartella di questo .bat
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "REQ_FILE=requirements.txt"

REM Trova un python (preferisce py launcher se presente)
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)

REM Crea venv se non esiste
if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [INFO] Creo la virtualenv in "%VENV_DIR%"...
  %PY% -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [ERRORE] Creazione venv fallita. Verifica Python installato.
    exit /b 1
  )
) else (
  echo [INFO] Virtualenv gia' presente: "%VENV_DIR%"
)

REM Aggiorna pip e installa dipendenze
echo [INFO] Aggiorno pip/setuptools/wheel...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 exit /b 1

if exist "%REQ_FILE%" (
  echo [INFO] Installo dipendenze da "%REQ_FILE%"...
  "%VENV_DIR%\Scripts\python.exe" -m pip install -r "%REQ_FILE%"
  if errorlevel 1 exit /b 1
) else (
  echo [ERRORE] Non trovo "%REQ_FILE%" in: %cd%
  exit /b 1
)

echo [OK] Ambiente pronto.
endlocal
