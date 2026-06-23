@echo off
REM Root launcher: build the H.265 Transcoder Windows installer.
REM Delegates to deploy\h265-transcoder\build.bat (stages payload, makes icon,
REM freezes the one-file setup exe). See deploy\h265-transcoder\README.md.
call "%~dp0deploy\h265-transcoder\build.bat" %*
