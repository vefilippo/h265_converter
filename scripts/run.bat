@echo off
REM Run: start the FastAPI + worker service standalone (serves the built web UI).
setlocal
cd /d "%~dp0..\source_code" || exit /b 1

if not exist ".venv\Scripts\python.exe" (
  echo [run] Virtual environment missing. Run scripts\build.bat first.
  exit /b 1
)
if not exist ".env" (
  echo [run] No .env found. Copy .env.example to .env and fill it in first.
  exit /b 1
)

echo [run] Starting H.265 transcoder service ^(Ctrl+C to stop^)...
call ".venv\Scripts\python.exe" -m transcoder.api
endlocal
