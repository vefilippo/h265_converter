"""Pure, side-effect-free helpers for the H.265 Transcoder Windows installer.

Everything here is unit-testable without Windows, a GUI, or subprocess/registry
access (see tests/test_installer_lib.py). The live I/O — running schtasks,
writing the registry, building the venv, driving the tkinter wizard — lives in
host_setup.py and stage_payload.py and imports these helpers.

Installed layout (per-user, %LOCALAPPDATA%):

    <install_dir>\
      h265-transcoder-setup.exe        # copy of the running installer (stable UninstallString)
      solution\                        # the payload == the repo build context
        tray.pyw
        transcoder\ ...
        .venv\Scripts\{pythonw,python}.exe
"""
from __future__ import annotations

import pathlib

APP_NAME = "H265Transcoder"          # task name + install-folder name + registry key
APP_DISPLAY = "H.265 Transcoder"     # Add/Remove Programs display name
PUBLISHER = "vefilippo"
SETUP_EXE = "h265-transcoder-setup.exe"
TASK_NAME = APP_NAME
PAYLOAD_DIRNAME = "solution"         # the build context dir name, bundled verbatim

# Relative to HKEY_CURRENT_USER (per-user; creating it needs no admin).
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\\" + APP_NAME


def default_install_dir(env=None) -> str:
    """Default per-user install dir: %LOCALAPPDATA%\\H265Transcoder.

    Per-user (not Program Files) because the app must run in the logged-in
    user's interactive session for GPU/NVENC + network-share access, and so the
    venv + app data live where that user can write them without elevation.
    """
    if env is None:
        import os
        env = os.environ
    base = env.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
    return str(pathlib.Path(base) / APP_NAME)


def payload_root(install_dir: str) -> str:
    return str(pathlib.Path(install_dir) / PAYLOAD_DIRNAME)


def tray_script(install_dir: str) -> str:
    return str(pathlib.Path(install_dir) / PAYLOAD_DIRNAME / "tray.pyw")


def venv_pythonw(install_dir: str) -> str:
    return str(pathlib.Path(install_dir) / PAYLOAD_DIRNAME / ".venv" / "Scripts" / "pythonw.exe")


def venv_python(install_dir: str) -> str:
    return str(pathlib.Path(install_dir) / PAYLOAD_DIRNAME / ".venv" / "Scripts" / "python.exe")


def setup_exe_path(install_dir: str) -> str:
    return str(pathlib.Path(install_dir) / SETUP_EXE)


def logon_task_tr(pythonw: str, tray: str) -> str:
    """The /tr value for schtasks: program + arg, each quoted, in ONE string.

    This is schtasks's own quoting (one argv element), not cmd's — passing it as
    a single argument to schtasks is correct (see windows-installer.md).
    """
    return f'"{pythonw}" "{tray}"'


def create_task_argv(task_name: str, pythonw: str, tray: str, highest: bool = True) -> list[str]:
    """schtasks argv to register an at-logon task for the current user.

    `highest=True` keeps `/rl highest`, matching the legacy install-service.bat
    (chosen for GPU + network-share access). For an onlogon task running as the
    current interactive user it still runs in-session.
    """
    argv = [
        "schtasks", "/create", "/tn", task_name,
        "/tr", logon_task_tr(pythonw, tray),
        "/sc", "onlogon", "/f",
    ]
    if highest:
        argv += ["/rl", "highest"]
    return argv


def delete_task_argv(task_name: str) -> list[str]:
    return ["schtasks", "/delete", "/tn", task_name, "/f"]


def uninstall_registry_values(install_dir: str, version: str) -> dict:
    """Values for HKCU\\...\\Uninstall\\H265Transcoder (Add/Remove Programs)."""
    exe = setup_exe_path(install_dir)
    return {
        "DisplayName": APP_DISPLAY,
        "DisplayVersion": version,
        "Publisher": PUBLISHER,
        "InstallLocation": install_dir,
        "DisplayIcon": exe,
        "UninstallString": f'"{exe}" --uninstall',
        "QuietUninstallString": f'"{exe}" --uninstall --quiet',
        "NoModify": 1,
        "NoRepair": 1,
    }


def shortcut_spec(install_dir: str, icon_path: str | None = None) -> dict:
    """Describe the desktop .lnk: pythonw.exe tray.pyw (no console window)."""
    return {
        "target": venv_pythonw(install_dir),
        "arguments": f'"{tray_script(install_dir)}"',
        "working_dir": payload_root(install_dir),
        "icon": icon_path or setup_exe_path(install_dir),
    }


def payload_should_ship(rel: str) -> bool:
    """True if a git-tracked path belongs in the bundled payload.

    We ship exactly the `solution/` build context and nothing else (tests, docs,
    deploy tooling stay out). Slash-agnostic so it works on git's posix paths
    and Windows paths alike.
    """
    return rel.replace("\\", "/").startswith(PAYLOAD_DIRNAME + "/")


def payload_dest(rel: str, dest_root: str) -> str:
    """Map a tracked path (e.g. solution/transcoder/x.py) under dest_root,
    preserving its relative tree."""
    rel_posix = rel.replace("\\", "/")
    return str(pathlib.Path(dest_root).joinpath(*rel_posix.split("/")))
