"""The tray must not leave the server writing into a pipe only the tray reads.

The tray used to start the server with stdout/stderr = PIPE and drain them on
daemon threads. Once that tray process died (or was replaced by a fresh tray,
which finds the server "already up" and adopts nothing), the server kept
running with a pipe nobody reads: every write to stderr then failed on
Windows with "[Errno 22] Invalid argument", which aborted every SFTP download.
The server's output must go to a file it owns, independent of the tray.
"""

import importlib.machinery
import importlib.util
import logging
import pathlib
import subprocess

import pytest

_TRAY = pathlib.Path(__file__).resolve().parents[1] / "solution" / "tray.pyw"


@pytest.fixture
def tray():
    before = list(logging.root.handlers)
    loader = importlib.machinery.SourceFileLoader("tray_under_test", str(_TRAY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    yield mod
    for h in list(logging.root.handlers):
        if h not in before:
            logging.root.removeHandler(h)
            h.close()


def _start(tray, monkeypatch, tmp_path):
    seen = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            seen.update(kwargs)
            out = kwargs.get("stdout")
            # The child must receive a real OS-level handle, not a pipe.
            seen["stdout_fileno"] = out.fileno() if hasattr(out, "fileno") else None

        def poll(self):
            return None

    monkeypatch.setattr(tray, "_LOG_DIR", tmp_path)
    monkeypatch.setattr(tray, "_is_up", lambda: False)
    monkeypatch.setattr(tray, "_server_proc", None)
    monkeypatch.setattr(tray.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(tray.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda self: None})())
    tray._start_server(None, None)
    return seen


def test_server_output_goes_to_a_file_not_a_pipe(tray, monkeypatch, tmp_path):
    seen = _start(tray, monkeypatch, tmp_path)

    assert seen["stdout"] is not subprocess.PIPE
    assert seen["stderr"] is not subprocess.PIPE
    assert seen["stdout_fileno"] is not None
    assert seen["stderr"] in (subprocess.STDOUT, seen["stdout"])


def test_server_output_file_is_server_start_log(tray, monkeypatch, tmp_path):
    seen = _start(tray, monkeypatch, tmp_path)

    assert pathlib.Path(seen["stdout"].name) == tmp_path / "server_start.log"
