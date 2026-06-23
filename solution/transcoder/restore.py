from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import socket
from pathlib import Path

MARKER = "RESTORE_PENDING"
PENDING_DIR = "restore_pending"


def stage_restore(db_bytes: bytes, env_text: str, base_dir: str) -> None:
    pend = Path(base_dir) / PENDING_DIR
    if pend.exists():
        shutil.rmtree(pend)
    pend.mkdir(parents=True)
    (pend / "transcoder.db").write_bytes(db_bytes)
    (pend / "env.txt").write_text(env_text, encoding="utf-8")
    # Marker written LAST so a half-staged restore is never applied.
    (pend / MARKER).write_text("", encoding="utf-8")


def apply_pending_restore(base_dir: str, db_path: str, env_path: str) -> bool:
    pend = Path(base_dir) / PENDING_DIR
    if not (pend / MARKER).exists():
        return False
    # Atomic DB swap: copy staged -> temp beside target -> os.replace.
    incoming = str(db_path) + ".incoming"
    shutil.copyfile(pend / "transcoder.db", incoming)
    os.replace(incoming, db_path)
    env_text = (pend / "env.txt").read_text(encoding="utf-8")
    if env_text:  # empty means the backup carried no .env — leave existing one
        env_incoming = str(env_path) + ".incoming"
        Path(env_incoming).write_text(env_text, encoding="utf-8")
        os.replace(env_incoming, env_path)
    shutil.rmtree(pend)
    return True


_DETACHED = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW


def relaunch_argv(python_exe: str, package_dir: str) -> list[str]:
    return [python_exe, "-m", "transcoder.api"]


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def schedule_relaunch(python_exe: str | None = None, package_dir: str | None = None,
                      port: int = 8765) -> None:
    """Spawn a detached process that waits for the port to free, then restarts
    the API. Survives this process exiting. Best-effort; not unit-tested."""
    python_exe = python_exe or sys.executable
    package_dir = package_dir or str(__import__("pathlib").Path(__file__).resolve().parent.parent)
    waiter = (
        "import socket,time,subprocess,sys\n"
        f"for _ in range(60):\n"
        f"    s=socket.socket()\n"
        f"    free=s.connect_ex(('127.0.0.1',{port}))!=0\n"
        f"    s.close()\n"
        f"    if free: break\n"
        f"    time.sleep(0.5)\n"
        f"subprocess.Popen([r'{python_exe}','-m','transcoder.api'], cwd=r'{package_dir}')\n"
    )
    subprocess.Popen([python_exe, "-c", waiter], creationflags=_DETACHED)
