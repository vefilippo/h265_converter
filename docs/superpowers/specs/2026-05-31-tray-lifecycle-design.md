# Design: Tray-owned server lifecycle at logon

**Date:** 2026-05-31  
**Status:** Approved

## Goal

At Windows logon, both the FastAPI server and the system tray app start automatically. The tray owns the server lifecycle: it starts the server on launch and stops it on exit.

## Approach

Single scheduled task (`H265Transcoder`) launches `pythonw.exe tray.pyw` at logon. The tray auto-starts the server immediately on launch. Exiting the tray (via menu → Exit) stops the server, as it already does today.

## Changes

### 1. `source_code/tray.pyw`

In `main()`, call `_start_server(None, None)` before `icon.run()`. The existing guard inside `_start_server` (`if _is_up(): return`) ensures no double-start if the server is already running.

### 2. `scripts/install-service.bat`

Change the scheduled task command from:
```
wscript.exe "run-hidden.vbs"
```
to:
```
"<venv>\Scripts\pythonw.exe" "<source_code>\tray.pyw"
```
`pythonw.exe` runs without a console window, so no VBS wrapper is needed. Update the help text to reflect that the tray (not the raw server) is what starts at logon.

### 3. `scripts/run-hidden.vbs`

No functional change. Update the leading comment to note it is now for headless-only use (server without tray), not the normal logon path.

### 4. `scripts/uninstall-service.bat`

Update the final echo hint: `scripts/tray.bat` is the normal manual start; `scripts/run.bat` is headless-only.

### 5. `scripts/tray.bat`

No change.

## Behaviour after the change

| Scenario | Before | After |
|---|---|---|
| Logon | Server starts, no tray | Server + tray start |
| Tray → Exit | Server stops | Server stops (unchanged) |
| Tray → Stop | Server stops | Server stops (unchanged) |
| Manual `run.bat` | Server only | Server only (unchanged) |
| Manual `tray.bat` | Tray only (no auto-start) | Tray + auto-starts server |

## Non-goals

- No change to headless server use (`run.bat` / `run-hidden.vbs`)
- No change to tray Start/Stop menu items
- No second scheduled task
