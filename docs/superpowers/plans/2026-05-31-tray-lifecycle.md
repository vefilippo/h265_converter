# Tray-Owned Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At Windows logon the tray starts automatically and immediately launches the FastAPI server; exiting the tray stops the server.

**Architecture:** The scheduled task `H265Transcoder` is retargeted from `run-hidden.vbs` (server only) to `pythonw.exe tray.pyw` (tray + auto-start server). `tray.pyw` calls `_start_server` in `main()` before entering the event loop. No second task; no new processes.

**Tech Stack:** Python / pystray, Windows Task Scheduler (`schtasks`), batch scripts

---

### Task 1: Auto-start server when tray launches

**Files:**
- Modify: `source_code/tray.pyw` (lines 242–256, `main()`)

- [ ] **Step 1: Open `source_code/tray.pyw` and locate `main()`**

  The function currently ends with:
  ```python
  threading.Thread(target=_poll, args=(icon,), daemon=True).start()
  icon.run()
  ```

- [ ] **Step 2: Add the auto-start call**

  Replace those two lines with:
  ```python
  threading.Thread(target=_poll, args=(icon,), daemon=True).start()
  _start_server(None, None)
  icon.run()
  ```

  `_start_server` already guards against double-start (`if _is_up(): return` and the `_server_proc` check), so this is safe whether or not the server is already running.

- [ ] **Step 3: Verify manually**

  Run the tray directly:
  ```
  source_code\.venv\Scripts\pythonw.exe source_code\tray.pyw
  ```
  Wait ~5 seconds, then open `http://localhost:8765` — the login page should appear without clicking "Start" in the tray menu.

- [ ] **Step 4: Commit**

  ```bash
  git add source_code/tray.pyw
  git commit -m "feat: tray auto-starts server on launch"
  ```

---

### Task 2: Retarget the scheduled task to the tray

**Files:**
- Modify: `scripts/install-service.bat`

- [ ] **Step 1: Open `scripts/install-service.bat`**

  Current relevant lines:
  ```bat
  set TASK=H265Transcoder
  set SCRIPT=%~dp0run-hidden.vbs
  ...
  schtasks /create /tn "%TASK%" /tr "wscript.exe \"%SCRIPT%\"" /sc onlogon /rl highest /f
  ```

- [ ] **Step 2: Replace with pythonw + tray.pyw**

  Replace the entire `setlocal` block (everything between `setlocal` and the first `echo`) with:
  ```bat
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
  ```

- [ ] **Step 3: Verify the script syntax**

  Run (does NOT install — just checks for bat syntax errors):
  ```
  cmd /c "scripts\install-service.bat" 2>&1 | head -5
  ```
  If the venv is missing it will print `[service] Registration failed` — that's fine; it means the script ran and schtasks rejected it, not a syntax error.

  To do a real smoke-test, run from an elevated prompt and then immediately delete the task:
  ```
  schtasks /delete /tn "H265Transcoder" /f
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add scripts/install-service.bat
  git commit -m "feat: install-service targets tray instead of run-hidden.vbs"
  ```

---

### Task 3: Update comments in run-hidden.vbs and uninstall-service.bat

**Files:**
- Modify: `scripts/run-hidden.vbs`
- Modify: `scripts/uninstall-service.bat`

- [ ] **Step 1: Update `run-hidden.vbs` comment**

  Replace the opening comment line:
  ```vbs
  ' Launches the H.265 transcoder service with no visible console window.
  ' Used by the scheduled task created by install-service.bat.
  ```
  with:
  ```vbs
  ' Launches the H.265 transcoder server (no console) WITHOUT the tray icon.
  ' Headless-only use. The normal logon path (install-service.bat) uses
  ' pythonw.exe tray.pyw directly instead.
  ```

- [ ] **Step 2: Update `uninstall-service.bat` hint**

  Find the final echo lines at the bottom:
  ```bat
  echo             Run scripts\run.bat to start manually, or scripts\install-service.bat to re-register.
  ```
  Replace with:
  ```bat
  echo             Run scripts\tray.bat to start normally ^(tray + server^).
  echo             Run scripts\run.bat for headless ^(server only, no tray^).
  echo             Run scripts\install-service.bat to re-register the logon task.
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add scripts/run-hidden.vbs scripts/uninstall-service.bat
  git commit -m "docs: update script comments for tray-owned lifecycle"
  ```
