import subprocess

import pytest

from transcoder import encoders
from transcoder.encoders import CPU, probe


@pytest.fixture(autouse=True)
def _clear_probe_memo():
    """The unknown-probe memo is module-level mutable state; a leak between
    tests would make failures depend on execution order."""
    encoders.reset_probe_cache()
    yield
    encoders.reset_probe_cache()

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


# ── Process-local memo of unknown probe results ──────────────────────────────
# The DB must never cache "unknown" (a broken HandBrake that gets fixed has to
# be picked up without a manual reset), but re-probing on every job costs a
# subprocess each time on a host whose banner we cannot read.


def test_unknown_probe_is_memoised_within_a_process(session, monkeypatch):
    calls = []

    def fake_probe(cli, timeout=30.0):
        calls.append(cli)
        return set(), set()          # unrecognised banner -> unknown

    monkeypatch.setattr(encoders, "probe", fake_probe)
    encoders.reset_probe_cache()

    for _ in range(3):
        assert encoders.get_or_detect_capabilities(session, "hb.exe") == (
            set(), set(), None
        )
    assert len(calls) == 1, "unknown result should be probed once per process"


def test_reset_probe_cache_forces_a_reprobe(session, monkeypatch):
    calls = []
    monkeypatch.setattr(
        encoders, "probe",
        lambda cli, timeout=30.0: (calls.append(cli), (set(), set()))[1],
    )
    encoders.reset_probe_cache()
    encoders.get_or_detect_capabilities(session, "hb.exe")
    encoders.reset_probe_cache()
    encoders.get_or_detect_capabilities(session, "hb.exe")
    assert len(calls) == 2


def test_memo_is_keyed_on_the_cli_path(session, monkeypatch):
    """A different binary is a different question -- changing the path must not
    inherit the old binary's 'unknown'."""
    calls = []
    monkeypatch.setattr(
        encoders, "probe",
        lambda cli, timeout=30.0: (calls.append(cli), (set(), set()))[1],
    )
    encoders.reset_probe_cache()
    encoders.get_or_detect_capabilities(session, "old.exe")
    encoders.get_or_detect_capabilities(session, "new.exe")
    assert calls == ["old.exe", "new.exe"]


def test_a_successful_probe_is_not_memoised_as_unknown(session, monkeypatch):
    """A good result goes to the DB; the memo must not shadow it."""
    monkeypatch.setattr(
        encoders, "probe", lambda cli, timeout=30.0: ({"vcn", "cpu"}, {"qsv"})
    )
    encoders.reset_probe_cache()
    available, unavailable, detected_at = encoders.get_or_detect_capabilities(
        session, "hb.exe"
    )
    assert available == {"vcn", "cpu"}
    assert detected_at is not None
