"""On failure, convert_with_handbrake must surface HandBrake's own output.

HandBrake's stderr is merged into stdout, so the diagnostic lines (e.g.
"avio_open2 failed ... Could not write to indicated output file") flow through
the progress loop and were previously discarded — a generic "HandBrake
conversion failed" was all that reached the logs. Retain a bounded tail and log
it when HandBrake exits non-zero so the real cause is visible.
"""
import logging

from transcoder import convert
from transcoder.convert import convert_with_handbrake


class FakeProcess:
    def __init__(self, lines, returncode):
        self.stdout = iter(lines)
        self.returncode = returncode

    def wait(self):
        return self.returncode


def test_failure_logs_handbrake_output_tail(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(convert.settings, "OUTPUT_FOLDER", str(tmp_path) + "/")
    inp = tmp_path / "in.mkv"
    inp.write_bytes(b"x" * 100)

    err_line = "ERROR: avio_open2 failed, errno -2: Could not write to indicated output file"
    lines = [
        "[00:00:00] Starting Task: Encoding Pass\n",
        err_line + "\n",
        "Encode failed (error 3).\n",
    ]
    monkeypatch.setattr(
        convert.subprocess, "Popen",
        lambda *a, **k: FakeProcess(lines, returncode=3),
    )

    with caplog.at_level(logging.ERROR, logger="transcoder"):
        out_file, excluded = convert_with_handbrake(str(inp), "name.mkv", "preset")

    assert out_file is None
    # The real HandBrake error must appear in the logs, not just a generic message.
    assert err_line in caplog.text
    assert "error 3" in caplog.text.lower()
