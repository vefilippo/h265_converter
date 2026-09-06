from transcoder import restore


def test_waiter_does_not_launch_when_port_stays_busy(monkeypatch):
    import socket
    import subprocess
    import time

    launched = []
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *a: 0)
    monkeypatch.setattr(time, "sleep", lambda *a: None)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: launched.append(a))
    try:
        exec(restore._waiter_script("python.exe", ".", 8765), {})
    except SystemExit:
        pass
    assert not launched


def test_waiter_waits_for_parent_exit_before_checking_port(monkeypatch):
    import ctypes
    import socket
    import subprocess
    import sys
    from types import SimpleNamespace

    events = []
    def open_process(*a):
        events.append("open")
        return 123
    def wait(*a):
        events.append("exit")
        return 0
    kernel = SimpleNamespace(OpenProcess=open_process, WaitForSingleObject=wait,
                             CloseHandle=lambda *a: events.append("close"))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: kernel, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *a: events.append("port") or 1)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: events.append("launch"))
    exec(restore._waiter_script("python.exe", ".", 8765, parent_pid=42), {})
    assert events == ["open", "exit", "close", "port", "launch"]


def test_relaunch_argv_runs_api_module():
    argv = restore.relaunch_argv(r"C:\app\.venv\Scripts\pythonw.exe", r"C:\app")
    assert argv[0].endswith("pythonw.exe")
    assert argv[1:] == ["-m", "transcoder.api"]


def test_waiter_script_compiles_even_with_quote_in_path():
    # repr-serialized paths must produce syntactically valid Python source,
    # even when a path contains a single quote or backslashes.
    src = restore._waiter_script(r"C:\a b\py's\python.exe", r"C:\pkg's dir", 8765)
    compile(src, "<waiter>", "exec")  # raises SyntaxError if the fix regresses
