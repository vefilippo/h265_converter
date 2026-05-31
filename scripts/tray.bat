@echo off
REM Launch the H265 Transcoder tray icon (no console window).
REM Double-click this file or add it to your startup folder.
set ROOT=%~dp0..
start "" "%ROOT%\source_code\.venv\Scripts\pythonw.exe" "%ROOT%\source_code\tray.pyw"
