from __future__ import annotations

import os
import shutil
import subprocess
import sys
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
    # The snapshot is a fully-checkpointed standalone DB; drop any stale WAL
    # sidecars from the previous instance so SQLite can't replay old frames
    # against the freshly restored DB.
    for _sidecar in (str(db_path) + "-wal", str(db_path) + "-shm"):
        try:
            os.remove(_sidecar)
        except FileNotFoundError:
            pass
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


def _waiter_script(python_exe: str, package_dir: str, port: int,
                   parent_pid: int | None = None) -> str:
    """Generate a detached waiter script using repr() for robust path serialization.

    repr() yields valid Python string literals for any path (quotes, backslashes),
    so the generated source cannot be broken by special characters in the path values.
    """
    # A free listening port does not mean shutdown has finished: the worker,
    # SSE requests and SQLite connections can still be draining. Wait for the
    # process to exit before the replacement is allowed to swap its database.
    wait_parent = ""
    if parent_pid is not None:
        wait_parent = (
            "if sys.platform == 'win32':\n"
            "    import ctypes\n"
            "    from ctypes import wintypes\n"
            "    k=ctypes.WinDLL('kernel32', use_last_error=True)\n"
            "    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]\n"
            "    k.OpenProcess.restype=wintypes.HANDLE\n"
            "    k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]\n"
            "    k.WaitForSingleObject.restype=wintypes.DWORD\n"
            "    k.CloseHandle.argtypes=[wintypes.HANDLE]\n"
            f"    h=k.OpenProcess(0x00100000,False,{parent_pid})\n"
            "    if h:\n"
            "        result=k.WaitForSingleObject(h,0xFFFFFFFF)\n"
            "        k.CloseHandle(h)\n"
            "        if result != 0: sys.exit(1)\n"
            "    elif ctypes.get_last_error() != 87: sys.exit(1)\n"
            "else:\n"
            "    while True:\n"
            f"        try: os.kill({parent_pid},0)\n"
            "        except ProcessLookupError: break\n"
            "        time.sleep(0.5)\n"
        )
    return (
        "import os,socket,time,subprocess,sys\n"
        + wait_parent +
        "for _ in range(60):\n"
        "    s=socket.socket()\n"
        "    s.settimeout(0.5)\n"
        f"    free=s.connect_ex(('127.0.0.1',{port}))!=0\n"
        "    s.close()\n"
        "    if free: break\n"
        "    time.sleep(0.5)\n"
        "else: sys.exit(1)\n"
        f"subprocess.Popen([{python_exe!r},'-m','transcoder.api'], cwd={package_dir!r})\n"
    )


def schedule_relaunch(python_exe: str | None = None, package_dir: str | None = None,
                      port: int = 8765) -> None:
    """Restart only after this process exits and releases its database handles."""
    python_exe = python_exe or sys.executable
    package_dir = package_dir or os.getcwd()
    waiter = _waiter_script(python_exe, package_dir, port, parent_pid=os.getpid())
    kwargs = {"creationflags": _DETACHED} if sys.platform == "win32" else {"start_new_session": True}
    subprocess.Popen([python_exe, "-c", waiter], **kwargs)
