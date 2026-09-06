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

REM Import names differ from pip names: pillow imports as PIL, sv-ttk as sv_ttk.
python -c "import PyInstaller, PIL, sv_ttk" >nul 2>&1
if errorlevel 1 (
    echo [build] installing missing Python build dependencies...
    python -m pip install --disable-pip-version-check pyinstaller pillow sv-ttk || (echo [build] dependency install failed & exit /b 1)
    python -c "import PyInstaller, PIL, sv_ttk" >nul 2>&1 || (echo [build] dependencies still unavailable after install - try: python -m pip install pyinstaller pillow sv-ttk & exit /b 1)
)

echo [build] staging payload (git ls-files solution + npm build)...
python stage_payload.py || (echo [build] stage failed & exit /b 1)

echo [build] generating icon...
python make_icon.py || (echo [build] icon failed & exit /b 1)

echo [build] freezing installer with PyInstaller...
REM Run PyInstaller as a module, not as a bare command: the console script only
REM resolves when Python's Scripts dir is on PATH, and -m also guarantees the
REM same interpreter the rest of this script uses.
REM Keep this on ONE line: caret continuation is fragile under cmd redirection.
python -m PyInstaller --onefile --windowed --uac-admin --name h265-transcoder-setup --icon app.ico --add-data "build\payload\solution;solution" --collect-data sv_ttk --paths . host_setup.py || (echo [build] pyinstaller failed & exit /b 1)

echo.
echo [build] Done -^> dist\h265-transcoder-setup.exe
echo         Double-click it on the target PC to install (UAC will elevate).
echo         Uninstall via Add/Remove Programs, or: h265-transcoder-setup.exe --uninstall
endlocal
