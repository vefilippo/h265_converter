# H.265 Transcoder — Windows installer

Builds a single double-clickable `h265-transcoder-setup.exe` that provisions a
Windows PC to run the transcoder (the heavy work — HandBrake NVENC on the GPU,
in the logged-in user's session — can't go in a Linux container, so this is the
Windows-installer deploy shape, not Docker).

## What it does on the target

Extract the bundled `solution/` payload → `%LOCALAPPDATA%\H265Transcoder\solution`,
build the venv + install deps, register the `H265Transcoder` at-logon scheduled
task (`/rl highest`, current user — GPU + network-share access), create a desktop
shortcut, and add an Add/Remove Programs entry. Re-running upgrades in place
(overlay copy refreshes code, keeps the venv + `.env`). `--uninstall` reverses it.

**Prerequisites on the target (not bundled):** Python 3.10+, HandBrake CLI, an
NVIDIA GPU for NVENC. The prebuilt web UI *is* bundled.

## Build

From the repo root: `build-host-setup.bat` (or `python` the steps directly).
Build machine needs `pip install pyinstaller pillow sv-ttk` and Node/npm.

1. `stage_payload.py` — whitelist-copies `git ls-files -- solution` into
   `build/payload/solution`, then runs the Vite build and copies the (gitignored)
   `web/dist` in explicitly. Secrets are gitignored, so they cannot be bundled.
2. `make_icon.py` — writes a multi-size `app.ico`.
3. `build.bat` — freezes `host_setup.py` with PyInstaller
   (`--onefile --windowed --uac-admin`, payload added as `solution`).

Output: `dist/h265-transcoder-setup.exe`.

## Files

| File | Role |
|---|---|
| `installer_lib.py` | Pure helpers (paths, schtasks argv, registry values, shortcut spec, payload mapping) — unit-tested, no Windows needed. |
| `host_setup.py` | Orchestrator + tkinter wizard; the live subprocess/registry/GUI I/O. Also `--uninstall [--quiet]`. |
| `stage_payload.py` | Git-tracked payload staging + web build. |
| `make_icon.py` | `app.ico` generator (Pillow). |
| `build.bat` | PyInstaller build (root launcher: `build-host-setup.bat`). |
| `tests/` | Unit tests for `installer_lib`. |

## Testing

`installer_lib` is unit-tested (run by the repo suite, `python -m pytest`). The
subprocess/registry/GUI I/O is live — smoke-test the **frozen** exe by
double-clicking once (the UAC prompt + real wizard can't be driven headlessly).
To validate the wizard UI without building, run `python host_setup.py` from a
checkout (dev mode: uses the checkout in place, skips extraction + registry).
