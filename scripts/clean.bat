@echo off
REM Clean: remove the Python venv and web build artifacts (node_modules + dist).
REM Does NOT touch your .env, transcoder.db, or source files.
setlocal
cd /d "%~dp0..\solution" || exit /b 1

echo [clean] This removes .venv, web\node_modules and web\dist.
choice /m "[clean] Proceed"
if errorlevel 2 (echo [clean] Aborted. & endlocal & exit /b 0)

if exist ".venv"            rmdir /s /q ".venv"            && echo [clean] removed .venv
if exist "web\node_modules" rmdir /s /q "web\node_modules" && echo [clean] removed web\node_modules
if exist "web\dist"         rmdir /s /q "web\dist"         && echo [clean] removed web\dist

echo [clean] Done. Run scripts\build.bat to rebuild.
endlocal
