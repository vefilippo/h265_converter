@echo off
REM Uninstall: stop and remove the H265Transcoder scheduled task (logon service).
REM Run as Administrator if the task was installed system-wide, or as the same
REM user who ran install-service.bat.
setlocal

echo [uninstall] Stopping H265Transcoder task (if running)...
schtasks /end /tn "H265Transcoder" 2>nul
if %errorlevel% neq 0 (
    echo [uninstall] Task was not running or already stopped.
)

echo [uninstall] Deleting H265Transcoder scheduled task...
schtasks /delete /tn "H265Transcoder" /f 2>nul
if %errorlevel% neq 0 (
    echo [uninstall] Task not found or could not be deleted.
) else (
    echo [uninstall] Scheduled task removed.
)

echo [uninstall] Killing any remaining python processes on port 8765...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765 "') do (
    echo [uninstall]   Killing PID %%a
    taskkill /PID %%a /F 2>nul
)

echo [uninstall] Done. The service has been stopped and removed.
echo             Run scripts\run.bat to start manually, or scripts\install-service.bat to re-register.
endlocal
