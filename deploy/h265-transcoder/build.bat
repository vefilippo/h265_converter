@echo off
REM Build the H.265 Transcoder Windows installer (one-file PyInstaller exe).
REM   0. install any missing Python build dependencies
REM   1. stage the payload from git-tracked files + build the web UI
REM   2. generate the app icon
REM   3. freeze host_setup.py with the payload bundled
REM
REM Output: deploy\h265-transcoder\dist\h265-transcoder-setup.exe
REM Requires (build machine): Python, and Node/npm for the web build.
REM The Python build dependencies (pyinstaller, pillow, sv-ttk) are installed
REM automatically below if they are missing. Node/npm cannot be, so it is only
REM checked for.
setlocal
cd /d "%~dp0" || exit /b 1

echo [build] checking build dependencies...
where npm >nul 2>&1 || (echo [build] npm not found on PATH - install Node.js from https://nodejs.org and re-run & exit /b 1)

REM Pick a real interpreter. On a fresh Windows box "python" is often only the
REM Microsoft Store placeholder alias (it prints "Python was not found"), while
REM the py launcher points at the actual install, so try py first.
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY (echo [build] Python not found - install it from https://www.python.org or disable the "python.exe" App execution alias & exit /b 1)
echo [build] using Python: %PY%

REM Import names differ from pip names: pillow imports as PIL, sv-ttk as sv_ttk.
%PY% -c "import PyInstaller, PIL, sv_ttk" >nul 2>&1
if errorlevel 1 (
    echo [build] installing missing Python build dependencies...
    %PY% -m pip install --disable-pip-version-check pyinstaller pillow sv-ttk || (echo [build] dependency install failed & exit /b 1)
    %PY% -c "import PyInstaller, PIL, sv_ttk" >nul 2>&1 || (echo [build] dependencies still unavailable after install - try: %PY% -m pip install pyinstaller pillow sv-ttk & exit /b 1)
)

echo [build] staging payload (git ls-files solution + npm build)...
%PY% stage_payload.py || (echo [build] stage failed & exit /b 1)

echo [build] generating icon...
%PY% make_icon.py || (echo [build] icon failed & exit /b 1)

echo [build] freezing installer with PyInstaller...
REM Run PyInstaller as a module, not as a bare command: the console script only
REM resolves when Python's Scripts dir is on PATH, and -m also guarantees the
REM same interpreter the rest of this script uses.
REM Keep this on ONE line: caret continuation is fragile under cmd redirection.
%PY% -m PyInstaller --onefile --windowed --uac-admin --name h265-transcoder-setup --icon app.ico --add-data "build\payload\solution;solution" --collect-data sv_ttk --paths . host_setup.py || (echo [build] pyinstaller failed & exit /b 1)

echo.
echo [build] Done -^> dist\h265-transcoder-setup.exe
echo         Double-click it on the target PC to install (UAC will elevate).
echo         Uninstall via Add/Remove Programs, or: h265-transcoder-setup.exe --uninstall
endlocal
