@echo off
REM Install: register a scheduled task to start the tray (+ server) at logon.
REM Runs as the logged-in user so it has GPU + network-share access.
setlocal
set TASK=H265Transcoder
set PYTHONW=%~dp0..\source_code\.venv\Scripts\pythonw.exe
set TRAY=%~dp0..\source_code\tray.pyw

echo [service] Registering scheduled task "%TASK%" to start at logon...
schtasks /create /tn "%TASK%" /tr "\"%PYTHONW%\" \"%TRAY%\"" /sc onlogon /rl highest /f
if errorlevel 1 (
  echo [service] Registration failed. Try again from an elevated ^(admin^) prompt.
  endlocal & exit /b 1
)

echo.
echo [service] Installed. The tray icon ^(+ server^) will start at next logon.
echo   Start now : schtasks /run /tn "%TASK%"
echo   Status    : schtasks /query /tn "%TASK%"
echo   Remove    : schtasks /delete /tn "%TASK%" /f
echo [service] The server UI is on the configured API_HOST:API_PORT ^(default :8765^).
endlocal
