@echo off
REM Install: register a scheduled task to start the service (hidden) at logon.
REM Runs as the logged-in user so it has GPU + network-share access.
setlocal
set TASK=H265Transcoder
set SCRIPT=%~dp0run-hidden.vbs

echo [service] Registering scheduled task "%TASK%" to start at logon...
schtasks /create /tn "%TASK%" /tr "wscript.exe \"%SCRIPT%\"" /sc onlogon /rl highest /f
if errorlevel 1 (
  echo [service] Registration failed. Try again from an elevated ^(admin^) prompt.
  endlocal & exit /b 1
)

echo.
echo [service] Installed. Useful commands:
echo   Start now : schtasks /run /tn "%TASK%"
echo   Status    : schtasks /query /tn "%TASK%"
echo   Remove    : schtasks /delete /tn "%TASK%" /f
echo [service] The service serves the UI on the configured API_HOST:API_PORT (default :8765).
endlocal
