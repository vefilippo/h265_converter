"""Regression: HandBrake writes to settings.OUTPUT_FOLDER, but nothing created
that directory. The repo happened to have ./out/ from earlier runs, so it worked
there; a fresh install has no ./out/, so HandBrakeCLI exits immediately with
"avio_open2 failed ... Could not write to indicated output file" (error 3) and
the job is recorded as "HandBrake conversion failed". convert_with_handbrake
must create the output directory before launching HandBrake.
"""
import os

from transcoder import convert
from transcoder.convert import convert_with_handbrake


class FakeProcess:
    def __init__(self, lines):
        self.stdout = iter(lines)
        self.returncode = 0

    def wait(self):
        return 0


def test_convert_creates_missing_output_dir(monkeypatch, tmp_path):
    out_dir = tmp_path / "out_does_not_exist_yet"
    monkeypatch.setattr(convert.settings, "OUTPUT_FOLDER", str(out_dir) + os.sep)

    inp = tmp_path / "in.mkv"
    inp.write_bytes(b"x" * 100)

    def fake_popen(cmd, *a, **k):
        # Emulate HandBrake writing its output file. This open() only succeeds if
        # convert_with_handbrake already created the directory — which is the fix.
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "wb") as fh:
            fh.write(b"y" * 10)
        return FakeProcess([])

    monkeypatch.setattr(convert.subprocess, "Popen", fake_popen)

    out_file, excluded = convert_with_handbrake(str(inp), "name.mkv", "preset")

    assert os.path.isdir(out_dir)
    assert out_file == str(out_dir) + os.sep + "name.mkv"
    assert excluded is False  # 10 bytes < 100 bytes
