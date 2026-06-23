@echo off
REM Build the H.265 Transcoder Windows installer (one-file PyInstaller exe).
REM   1. stage the payload from git-tracked files + build the web UI
REM   2. generate the app icon
REM   3. freeze host_setup.py with the payload bundled
REM
REM Output: deploy\h265-transcoder\dist\h265-transcoder-setup.exe
REM Requires (build machine): Python with pyinstaller + Pillow + sv-ttk, and
REM Node/npm (for the web build). Install with:
REM   pip install pyinstaller pillow sv-ttk
setlocal
cd /d "%~dp0" || exit /b 1

echo [build] staging payload (git ls-files solution + npm build)...
python stage_payload.py || (echo [build] stage failed & exit /b 1)

echo [build] generating icon...
python make_icon.py || (echo [build] icon failed & exit /b 1)

echo [build] freezing installer with PyInstaller...
REM Keep this on ONE line: caret continuation is fragile under cmd redirection.
pyinstaller --onefile --windowed --uac-admin --name h265-transcoder-setup --icon app.ico --add-data "build\payload\solution;solution" --collect-data sv_ttk --paths . host_setup.py || (echo [build] pyinstaller failed & exit /b 1)

echo.
echo [build] Done -^> dist\h265-transcoder-setup.exe
echo         Double-click it on the target PC to install (UAC will elevate).
echo         Uninstall via Add/Remove Programs, or: h265-transcoder-setup.exe --uninstall
endlocal
