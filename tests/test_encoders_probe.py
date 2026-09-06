import subprocess

from transcoder import encoders
from transcoder.encoders import CPU, probe

# The unknown-probe memo is process-global mutable state. It is cleared for
# EVERY test by the autouse `_no_encoder_probe` fixture in tests/conftest.py --
# a module-local fixture here would leave the leak open for every other module.

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


def _fake_clock(monkeypatch, start=1000.0):
    """Drive the memo's clock by hand: {"t": ...}; mutate to advance time."""
    clock = {"t": start}
    monkeypatch.setattr(encoders, "_now", lambda: clock["t"])
    return clock


def test_memoised_unknown_is_not_reprobed_before_the_ttl(session, monkeypatch):
    calls = []
    monkeypatch.setattr(
        encoders, "probe",
        lambda cli, timeout=30.0: (calls.append(cli), (set(), set()))[1],
    )
    clock = _fake_clock(monkeypatch)

    encoders.get_or_detect_capabilities(session, "hb.exe")
    clock["t"] += encoders.PROBE_MEMO_TTL_SECONDS - 1
    encoders.get_or_detect_capabilities(session, "hb.exe")

    assert len(calls) == 1, "memo should still be serving inside the TTL"


def test_memoised_unknown_is_reprobed_after_the_ttl(session, monkeypatch):
    """A probe failure may be transient (timeout on a busy box, an antivirus
    lock, a truncated banner). Hardening it for the whole process lifetime would
    pin `auto` to CPU x265 until restart, so the memo expires."""
    calls = []
    monkeypatch.setattr(
        encoders, "probe",
        lambda cli, timeout=30.0: (calls.append(cli), (set(), set()))[1],
    )
    clock = _fake_clock(monkeypatch)

    encoders.get_or_detect_capabilities(session, "hb.exe")
    clock["t"] += encoders.PROBE_MEMO_TTL_SECONDS + 1
    encoders.get_or_detect_capabilities(session, "hb.exe")

    assert len(calls) == 2, "an expired memo entry must re-probe"


def test_a_transient_probe_failure_self_heals_once_the_ttl_elapses(
    session, monkeypatch
):
    results = [(set(), set()), ({"vcn", CPU}, {"qsv"})]
    monkeypatch.setattr(
        encoders, "probe", lambda cli, timeout=30.0: results.pop(0)
    )
    clock = _fake_clock(monkeypatch)

    assert encoders.get_or_detect_capabilities(session, "hb.exe") == (
        set(), set(), None
    )
    clock["t"] += encoders.PROBE_MEMO_TTL_SECONDS + 1
    available, unavailable, detected_at = encoders.get_or_detect_capabilities(
        session, "hb.exe"
    )
    assert (available, unavailable) == ({"vcn", CPU}, {"qsv"})
    assert detected_at is not None


def test_a_successful_probe_clears_the_unknown_memo_entry(session, monkeypatch):
    """Otherwise a stale entry would keep costing a dict lookup forever and,
    worse, could out-live a path that has since been re-detected fine."""
    results = [(set(), set()), ({"vcn", CPU}, {"qsv"})]
    monkeypatch.setattr(
        encoders, "probe", lambda cli, timeout=30.0: results.pop(0)
    )
    clock = _fake_clock(monkeypatch)

    encoders.get_or_detect_capabilities(session, "hb.exe")
    clock["t"] += encoders.PROBE_MEMO_TTL_SECONDS + 1
    encoders.get_or_detect_capabilities(session, "hb.exe")

    assert "hb.exe" not in encoders._unknown_probes


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
