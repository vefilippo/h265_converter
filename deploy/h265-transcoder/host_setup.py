"""H.265 Transcoder — Windows self-contained installer / uninstaller.

One double-clickable exe (built by build.bat) that provisions this machine:
extract the bundled `solution/` payload to %LOCALAPPDATA%\\H265Transcoder, build
the venv, install deps, register an at-logon scheduled task, make a desktop
shortcut, and register an Add/Remove Programs entry. `--uninstall` reverses it.

Prerequisites on the target (NOT bundled): Python 3.10+, Node/npm on PATH (only
if you build from a dev checkout — the shipped exe bundles the prebuilt web UI),
HandBrake CLI, and an NVIDIA GPU for NVENC. The wizard's first page states this.

Pure helpers live in installer_lib.py (unit-tested). This module is the live
subprocess/registry/GUI I/O — smoke-tested by running the frozen exe once.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import installer_lib as lib

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
VERSION = "1.0.0"

# --- output sink (NEVER bare print(): --windowed builds have no stdout) --------
_LOG_FILE = Path(os.environ.get("TEMP", ".")) / "h265-transcoder-setup.log"


def _emit(msg: str, sink=None) -> None:
    if sink is not None:
        try:
            sink(msg)
        except Exception:
            pass
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except Exception:
        pass


def _run(argv, sink=None, cwd=None, check=True):
    _emit("  $ " + " ".join(str(a) for a in argv), sink)
    res = subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True,
        creationflags=CREATE_NO_WINDOW,
    )
    if res.stdout:
        _emit(res.stdout.strip(), sink)
    if res.returncode != 0:
        _emit(f"  ! exit {res.returncode}: {res.stderr.strip()}", sink)
        if check:
            raise RuntimeError(f"command failed: {argv}")
    return res


# --- payload resolution: shipped exe vs dev checkout ---------------------------
def bundled_payload() -> Path | None:
    """Return the bundled payload root (…/solution) if running as the frozen exe."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    cand = Path(base) / lib.PAYLOAD_DIRNAME
    return cand if (cand / "tray.pyw").exists() else None


def dev_checkout_payload() -> Path | None:
    """When run as host_setup.py from the repo, use the checkout in place."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    cand = repo_root / lib.PAYLOAD_DIRNAME
    return cand if (cand / "tray.pyw").exists() else None


# --- install -------------------------------------------------------------------
def install(install_dir: str | None = None, sink=None) -> str:
    install_dir = install_dir or lib.default_install_dir()
    inst = Path(install_dir)
    payload_src = bundled_payload()
    is_frozen = payload_src is not None

    _emit(f"[install] target: {inst}", sink)
    inst.mkdir(parents=True, exist_ok=True)

    if is_frozen:
        # _MEIPASS is a temp dir wiped on exit — copy the payload to the
        # persistent install dir first, then build the venv there. Overlay
        # (dirs_exist_ok) refreshes code on re-run while keeping venv + .env.
        _emit("[install] copying payload …", sink)
        shutil.copytree(payload_src, inst / lib.PAYLOAD_DIRNAME, dirs_exist_ok=True)
        # Copy the running exe in so UninstallString points at a stable file.
        try:
            shutil.copy2(sys.executable, lib.setup_exe_path(str(inst)))
        except Exception as exc:
            _emit(f"[install] (warning) could not copy setup exe: {exc}", sink)
    else:
        dev = dev_checkout_payload()
        _emit(f"[install] dev mode — using checkout in place: {dev}", sink)

    payload = inst / lib.PAYLOAD_DIRNAME

    _emit("[install] creating venv + installing deps …", sink)
    venv_py = Path(lib.venv_python(str(inst)))
    if not venv_py.exists():
        _run([sys.executable if not is_frozen else "python", "-m", "venv",
              str(payload / ".venv")], sink=sink)
    _run([str(venv_py), "-m", "pip", "install", "--upgrade", "pip"], sink=sink)
    _run([str(venv_py), "-m", "pip", "install", "-r",
          str(payload / "requirements.txt")], sink=sink)

    _emit("[install] registering logon task …", sink)
    _run(lib.create_task_argv(lib.TASK_NAME, lib.venv_pythonw(str(inst)),
                              lib.tray_script(str(inst))), sink=sink)

    if is_frozen:
        _emit("[install] desktop shortcut + Add/Remove Programs entry …", sink)
        _create_shortcut(str(inst), sink)
        _write_uninstall_registry(str(inst), sink)

    _emit("[install] done. The tray + server start at next logon "
          "(start now: schtasks /run /tn H265Transcoder).", sink)
    return str(inst)


def _create_shortcut(install_dir: str, sink=None) -> None:
    spec = lib.shortcut_spec(install_dir)
    lnk = Path(os.environ.get("USERPROFILE", ".")) / "Desktop" / f"{lib.APP_DISPLAY}.lnk"
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath='%s';$s.Arguments='%s';$s.WorkingDirectory='%s';"
        "$s.IconLocation='%s';$s.Save()"
    ) % (lnk, spec["target"], spec["arguments"].replace("'", "''"),
         spec["working_dir"], spec["icon"])
    _run(["powershell", "-NoProfile", "-Command", ps], sink=sink, check=False)


def _write_uninstall_registry(install_dir: str, sink=None) -> None:
    import winreg
    vals = lib.uninstall_registry_values(install_dir, VERSION)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, lib.UNINSTALL_KEY) as key:
        for name, val in vals.items():
            if isinstance(val, int):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, val)
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, val)
    _emit("[install] registered uninstall entry", sink)


# --- uninstall -----------------------------------------------------------------
def uninstall(install_dir: str | None = None, sink=None) -> None:
    install_dir = install_dir or lib.default_install_dir()
    inst = Path(install_dir)
    _emit(f"[uninstall] {inst}", sink)

    _stop_app(install_dir, sink)
    _run(lib.delete_task_argv(lib.TASK_NAME), sink=sink, check=False)

    lnk = Path(os.environ.get("USERPROFILE", ".")) / "Desktop" / f"{lib.APP_DISPLAY}.lnk"
    try:
        lnk.unlink(missing_ok=True)
    except Exception:
        pass

    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, lib.UNINSTALL_KEY)
    except Exception:
        pass

    _schedule_self_delete(install_dir, sink)
    _emit("[uninstall] done.", sink)


def _stop_app(install_dir: str, sink=None) -> None:
    """Stop only THIS install's tray (match command line scoped to the install
    dir — never blanket-kill pythonw.exe)."""
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
        "Where-Object { $_.CommandLine -like '*%s*tray.pyw*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    ) % install_dir.replace("\\", "\\\\")
    _run(["powershell", "-NoProfile", "-Command", ps], sink=sink, check=False)


def _schedule_self_delete(install_dir: str, sink=None) -> None:
    """The exe lives inside install_dir and can't delete itself — spawn a
    detached .bat that waits, removes the dir, then deletes itself."""
    bat = Path(os.environ.get("TEMP", ".")) / "h265-transcoder-uninstall.bat"
    bat.write_text(
        "@echo off\r\n"
        "ping 127.0.0.1 -n 3 >nul\r\n"
        f'rmdir /s /q "{install_dir}"\r\n'
        '(goto) 2>nul & del "%~f0"\r\n',
        encoding="utf-8",
    )
    subprocess.Popen(["cmd", "/c", str(bat)],
                     creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW)
    _emit("[uninstall] scheduled folder removal", sink)


# --- GUI wizard (tkinter + ttk + sv-ttk, degrades gracefully) ------------------
def run_gui(do_uninstall: bool) -> None:
    import tkinter as tk
    from tkinter import ttk, filedialog

    root = tk.Tk()
    root.title(f"{lib.APP_DISPLAY} — {'Uninstall' if do_uninstall else 'Setup'}")
    root.geometry("640x460")
    try:
        import sv_ttk
        sv_ttk.set_theme("dark")
    except Exception:
        pass  # plain ttk if the theme data wasn't bundled

    intro = (
        "This will remove H.265 Transcoder from this PC."
        if do_uninstall else
        "Installs H.265 Transcoder for the current user.\n\n"
        "Requires (not bundled): Python 3.10+, HandBrake CLI, and an NVIDIA GPU "
        "for NVENC. The service starts automatically at logon."
    )
    ttk.Label(root, text=intro, wraplength=600, justify="left").pack(padx=16, pady=12, anchor="w")

    dir_var = tk.StringVar(value=lib.default_install_dir())
    if not do_uninstall:
        row = ttk.Frame(root); row.pack(fill="x", padx=16)
        ttk.Label(row, text="Install location:").pack(side="left")
        ttk.Entry(row, textvariable=dir_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="Browse…",
                   command=lambda: dir_var.set(filedialog.askdirectory() or dir_var.get())
                   ).pack(side="left")

    logbox = tk.Text(root, height=14, wrap="word")
    logbox.pack(fill="both", expand=True, padx=16, pady=12)
    q: queue.Queue[str] = queue.Queue()

    def drain():
        while not q.empty():
            logbox.insert("end", q.get() + "\n")
            logbox.see("end")
        root.after(120, drain)

    def worker():
        try:
            if do_uninstall:
                uninstall(dir_var.get(), sink=q.put)
            else:
                install(dir_var.get(), sink=q.put)
            q.put("\n✓ Finished. You may close this window.")
        except Exception as exc:  # noqa: BLE001
            q.put(f"\n✗ Failed: {exc}")

    def go():
        run_btn.config(state="disabled")
        threading.Thread(target=worker, daemon=True).start()

    run_btn = ttk.Button(root, text=("Uninstall" if do_uninstall else "Install"), command=go)
    run_btn.pack(pady=(0, 12))

    drain()
    root.mainloop()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    do_uninstall = "--uninstall" in argv
    quiet = "--quiet" in argv
    if quiet:
        (uninstall if do_uninstall else install)(sink=lambda m: _emit(m))
        return 0
    run_gui(do_uninstall)
    return 0


if __name__ == "__main__":
    sys.exit(main())
