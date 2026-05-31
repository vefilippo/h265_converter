# Scripts

Windows helper scripts for the H.265 transcoder service. Run them from anywhere
(they resolve paths relative to themselves). Requires Python and Node/npm on PATH.

| Script | What it does |
|---|---|
| `build.bat` | Create `source_code/.venv`, install backend deps, `npm install` + `npm run build` the web UI. |
| `run.bat` | Start the service standalone (FastAPI + worker, serving the built UI). Needs `.env`. |
| `clean.bat` | Remove `.venv`, `web/node_modules`, `web/dist` (asks for confirmation). Leaves `.env`/DB/source intact. |
| `install-service.bat` | Register a scheduled task to start the service **hidden at logon** (via `run-hidden.vbs`). |
| `uninstall-service.bat` | Stop and delete the `H265Transcoder` scheduled task, then kill any process still on port 8765. |
| `run-hidden.vbs` | Helper that launches `run.bat` with no console window (used by the scheduled task). |
| `tray.bat` | Start the system tray icon (no console). Green = server up, grey = down. Right-click: Open UI / Start / Stop / Exit. Sends Windows toast notifications on job completion. |

## Typical flow

```bat
scripts\build.bat
copy source_code\.env.example source_code\.env   REM then edit .env
scripts\run.bat                                   REM open http://localhost:8765
```

## Run on boot

`scripts\install-service.bat` registers a **Scheduled Task** that starts the service
at logon as the current user (so it has access to the GPU and your network shares).
Manage it with:

```bat
schtasks /run    /tn "H265Transcoder"   REM start now
schtasks /query  /tn "H265Transcoder"   REM status
schtasks /delete /tn "H265Transcoder" /f  REM remove
```

A logon-task runs only after you sign in. If you need it to run with no user logged
in (a true background service), use **NSSM** instead:

```bat
nssm install H265Transcoder "C:\...\source_code\.venv\Scripts\python.exe" "-m" "transcoder.api"
nssm set     H265Transcoder AppDirectory "C:\...\source_code"
nssm start   H265Transcoder
```

Note: HandBrake NVENC needs a GPU-capable session; the logon-task approach is the
simplest reliable option on a desktop box.
