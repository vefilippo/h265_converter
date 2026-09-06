import subprocess

from transcoder.encoders import CPU, probe

AMD_BANNER = """[17:01:27] Compile-time hardening features are enabled
Cannot load nvEncodeAPI64.dll
[17:01:27] vcn: is available
[17:01:27] qsv: not available on this system
HandBrake 1.11.2
"""


class _Completed:
    def __init__(self, stdout):
        self.stdout = stdout
        self.returncode = 0


def test_probe_runs_version_and_parses_output(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _Completed(AMD_BANNER)

    monkeypatch.setattr(subprocess, "run", fake_run)
    # (available, unavailable): the negatives are carried alongside the
    # positives so resolve() can tell "explicitly absent" from "never mentioned".
    assert probe("C:/HandBrake/HandBrakeCLI.exe") == ({"vcn", CPU}, {"qsv", "nvenc"})
    assert captured["cmd"] == ["C:/HandBrake/HandBrakeCLI.exe", "--version"]
    # stderr must be folded into stdout: HandBrake writes the banner to stderr.
    assert captured["kwargs"]["stderr"] == subprocess.STDOUT


def test_probe_returns_unknown_when_executable_is_missing(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe("nope.exe") == (set(), set())


def test_probe_returns_unknown_on_timeout(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe("slow.exe") == (set(), set())


def test_probe_returns_unknown_for_blank_path(monkeypatch):
    called = {"n": 0}

    def fake_run(cmd, **kwargs):
        called["n"] += 1
        return _Completed(AMD_BANNER)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe("") == (set(), set())
    assert called["n"] == 0  # must not shell out with an empty path


def test_probe_never_raises_on_unexpected_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe("x.exe") == (set(), set())
