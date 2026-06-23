import threading
import pytest

from transcoder import convert
from transcoder.convert import TranscodeCancelled, convert_with_handbrake


class FakeProcess:
    def __init__(self, lines):
        self.stdout = iter(lines)
        self.returncode = 0
        self.killed = False

    def kill(self):
        self.killed = True

    def wait(self):
        return 0


def test_convert_raises_and_kills_on_cancel(monkeypatch):
    proc = FakeProcess([
        "Encoding: task 1 of 1, 10.00 %\n",
        "Encoding: task 1 of 1, 20.00 %\n",
        "Encoding: task 1 of 1, 30.00 %\n",
    ])
    monkeypatch.setattr(convert.subprocess, "Popen", lambda *a, **k: proc)

    cancel = threading.Event()
    seen = []

    def cb(pct):
        seen.append(pct)
        if pct >= 20:
            cancel.set()  # request cancel after some progress

    with pytest.raises(TranscodeCancelled):
        convert_with_handbrake("in.mkv", "out.mkv", "preset",
                               progress_cb=cb, cancel_event=cancel)

    assert proc.killed is True
