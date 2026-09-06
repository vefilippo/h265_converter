# AMD Encoder Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the transcoder work on AMD/Intel/CPU hardware by turning the HandBrake encoder into a detectable, selectable setting instead of a hardcoded NVENC assumption.

**Architecture:** A new pure-ish module `transcoder/encoders.py` owns a family→preset catalog, a parser for HandBrake's startup capability banner, a subprocess probe, and preset resolution. Three new key/value settings (`encoder_family`, `encoder_fallback_cpu`, `encoder_capabilities`) thread through the existing settings machinery — no schema change. The worker resolves presets per job and substitutes CPU x265 only when a hardware family is *known* unavailable.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pytest; React + TypeScript + Tailwind, TanStack Query, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-05-amd-encoder-support-design.md`

## Global Constraints

- Branch: `feat/amd-encoder-support` (already created; the spec commit is `d56bfb0`).
- TDD is mandatory per `CLAUDE.md`: write the failing test, watch it fail, then implement.
- Backend tests run from the **repo root**: `python -m pytest` (`pytest.ini` sets `pythonpath = solution`). Never `cd solution` to run pytest.
- Frontend tests run from `solution/web`: `npm test` (runs `tsc -b` first, so type errors fail the suite).
- Preset strings are **verbatim** from HandBrakeCLI 1.11.2 and must not be reworded:
  - `H.265 VCN 1080p` / `H.265 VCN 2160p 4K`
  - `H.265 NVENC 1080p` / `H.265 NVENC 2160p 4K`
  - `H.265 QSV 1080p` / `H.265 QSV 2160p 4K`
  - `H.265 MKV 1080p30` / `H.265 MKV 2160p60 4K`
- Family ids are exactly `auto`, `vcn`, `nvenc`, `qsv`, `cpu`, `custom`. `mf` is deliberately excluded.
- Auto-selection priority is exactly `vcn` > `nvenc` > `qsv` > `cpu`.
- **Unknown is not unavailable:** CPU fallback fires only when capabilities are known and the family is absent from them. A failed probe never substitutes for an explicitly chosen family.
- Never use PowerShell here-strings or bash heredocs for commit messages (see `CLAUDE.md` Windows Notes). Use plain single-line `-m`.
- No `--no-verify`, no bypassing signing.

---

### Task 1: Encoder catalog, banner parser, and resolution (pure core)

Creates the heart of the feature with zero I/O, so it is entirely unit-testable.

**Files:**
- Create: `solution/transcoder/encoders.py`
- Test: `tests/test_encoders.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `FAMILIES: dict[str, dict]` — keys `vcn|nvenc|qsv|cpu`, each `{"label": str, "preset_1080": str, "preset_4k": str, "hardware": bool}`
  - `AUTO = "auto"`, `CUSTOM = "custom"`, `CPU = "cpu"`
  - `AUTO_PRIORITY: tuple[str, ...]`
  - `Resolution` frozen dataclass with fields `preset_1080: str`, `preset_4k: str`, `family: str`, `requested: str`, `substituted: bool`, `detection_unknown: bool`
  - `parse_capabilities(banner: str) -> set[str]`
  - `resolve(family: str, available: set[str], *, fallback_cpu: bool = True, custom_1080: str = "", custom_4k: str = "") -> Resolution`
  - `infer_family(preset_1080: str, preset_4k: str) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_encoders.py`:

```python
from transcoder import encoders
from transcoder.encoders import AUTO, CPU, CUSTOM, infer_family, parse_capabilities, resolve

# Captured verbatim from HandBrakeCLI 1.11.2 on an AMD Ryzen 9800X3D / RX 9070 XT
# box. Real output, not invented: NVENC fails to load, VCN is present, QSV is not.
AMD_BANNER = """[17:01:27] Compile-time hardening features are enabled
Cannot load nvEncodeAPI64.dll
[17:01:27] vcn: is available
[17:01:27] qsv: not available on this system
[17:01:27] hb_init: starting libhb thread
[17:01:27] thread 2 started ("libhb")
HandBrake 1.11.2
"""

NVIDIA_BANNER = """[10:00:00] Compile-time hardening features are enabled
[10:00:00] nvenc: is available
[10:00:00] vcn: not available on this system
[10:00:00] qsv: not available on this system
"""

INTEL_BANNER = """[10:00:00] qsv: is available
[10:00:00] nvenc: not available on this system
"""


def test_parse_amd_banner_finds_vcn_and_cpu():
    assert parse_capabilities(AMD_BANNER) == {"vcn", CPU}


def test_parse_treats_nvenc_dll_failure_as_unavailable():
    assert "nvenc" not in parse_capabilities(AMD_BANNER)


def test_parse_does_not_confuse_not_available_with_available():
    assert "qsv" not in parse_capabilities(AMD_BANNER)


def test_parse_nvidia_banner():
    assert parse_capabilities(NVIDIA_BANNER) == {"nvenc", CPU}


def test_parse_intel_banner():
    assert parse_capabilities(INTEL_BANNER) == {"qsv", CPU}


def test_parse_always_includes_cpu_even_for_empty_output():
    # A successful parse always yields at least cpu; the EMPTY set is reserved
    # by probe() to mean "capabilities unknown".
    assert parse_capabilities("") == {CPU}


def test_auto_prefers_vcn_over_cpu():
    r = resolve(AUTO, {"vcn", CPU})
    assert r.family == "vcn"
    assert r.preset_1080 == "H.265 VCN 1080p"
    assert r.preset_4k == "H.265 VCN 2160p 4K"
    assert r.substituted is False


def test_auto_priority_order_is_vcn_nvenc_qsv_cpu():
    assert resolve(AUTO, {"vcn", "nvenc", "qsv", CPU}).family == "vcn"
    assert resolve(AUTO, {"nvenc", "qsv", CPU}).family == "nvenc"
    assert resolve(AUTO, {"qsv", CPU}).family == "qsv"
    assert resolve(AUTO, {CPU}).family == CPU


def test_auto_with_unknown_capabilities_falls_to_cpu_and_flags_unknown():
    r = resolve(AUTO, set())
    assert r.family == CPU
    assert r.detection_unknown is True
    assert r.substituted is False


def test_explicit_available_family_is_used_as_is():
    r = resolve("nvenc", {"nvenc", CPU})
    assert r.family == "nvenc"
    assert r.preset_1080 == "H.265 NVENC 1080p"
    assert r.substituted is False


def test_explicit_unavailable_family_falls_back_to_cpu_when_enabled():
    r = resolve("nvenc", {"vcn", CPU}, fallback_cpu=True)
    assert r.family == CPU
    assert r.requested == "nvenc"
    assert r.substituted is True
    assert r.preset_1080 == "H.265 MKV 1080p30"
    assert r.preset_4k == "H.265 MKV 2160p60 4K"


def test_explicit_unavailable_family_runs_as_configured_when_fallback_disabled():
    r = resolve("nvenc", {"vcn", CPU}, fallback_cpu=False)
    assert r.family == "nvenc"
    assert r.substituted is False


def test_unknown_capabilities_never_substitute_an_explicit_family():
    # "Unknown is not unavailable" — a broken probe must not override a
    # deliberate choice, even with fallback enabled.
    r = resolve("nvenc", set(), fallback_cpu=True)
    assert r.family == "nvenc"
    assert r.substituted is False
    assert r.detection_unknown is True


def test_custom_passes_through_free_text_presets():
    r = resolve(CUSTOM, {"vcn", CPU}, custom_1080="My 1080", custom_4k="My 4K")
    assert r.family == CUSTOM
    assert r.preset_1080 == "My 1080"
    assert r.preset_4k == "My 4K"
    assert r.substituted is False


def test_custom_is_never_substituted_even_when_unavailable():
    r = resolve(CUSTOM, set(), fallback_cpu=True, custom_1080="X", custom_4k="Y")
    assert r.family == CUSTOM
    assert r.substituted is False


def test_infer_family_matches_catalog_presets():
    assert infer_family("H.265 VCN 1080p", "H.265 VCN 2160p 4K") == "vcn"
    assert infer_family("H.265 NVENC 1080p", "H.265 NVENC 2160p 4K") == "nvenc"
    assert infer_family("H.265 QSV 1080p", "H.265 QSV 2160p 4K") == "qsv"
    assert infer_family("H.265 MKV 1080p30", "H.265 MKV 2160p60 4K") == CPU


def test_infer_family_returns_auto_for_empty_presets():
    assert infer_family("", "") == AUTO


def test_infer_family_returns_custom_for_unrecognised_presets():
    assert infer_family("Fast 1080p30", "Fast 2160p60") == CUSTOM


def test_infer_family_returns_custom_for_mismatched_pair():
    # A half-matching pair is a hand-tuned setup; preserve it verbatim.
    assert infer_family("H.265 VCN 1080p", "H.265 NVENC 2160p 4K") == CUSTOM


def test_mf_is_not_in_the_catalog():
    assert "mf" not in encoders.FAMILIES
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_encoders.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'transcoder.encoders'`

- [ ] **Step 3: Write the implementation**

Create `solution/transcoder/encoders.py`:

```python
"""HandBrake encoder families: catalog, capability detection, preset resolution.

The transcoder used to hardcode NVENC presets, which fail on any non-NVIDIA host.
This module makes the encoder a first-class, detectable choice.

Everything here is pure except ``probe()``, which shells out to HandBrakeCLI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

AUTO = "auto"
CUSTOM = "custom"
CPU = "cpu"

# Preset names are verbatim from HandBrakeCLI 1.11.2 --preset-list. Note that
# AMD presets are named "VCN" (HandBrake 1.11 renamed them) even though the
# underlying encoder ids are still vce_h265 / vce_h265_10bit.
FAMILIES: dict[str, dict] = {
    "vcn": {
        "label": "AMD VCN",
        "preset_1080": "H.265 VCN 1080p",
        "preset_4k": "H.265 VCN 2160p 4K",
        "hardware": True,
    },
    "nvenc": {
        "label": "NVIDIA NVENC",
        "preset_1080": "H.265 NVENC 1080p",
        "preset_4k": "H.265 NVENC 2160p 4K",
        "hardware": True,
    },
    "qsv": {
        "label": "Intel QSV",
        "preset_1080": "H.265 QSV 1080p",
        "preset_4k": "H.265 QSV 2160p 4K",
        "hardware": True,
    },
    "cpu": {
        "label": "CPU (x265)",
        "preset_1080": "H.265 MKV 1080p30",
        "preset_4k": "H.265 MKV 2160p60 4K",
        "hardware": False,
    },
}

# Hardware before software; on a multi-GPU host the discrete vendor encoder wins.
AUTO_PRIORITY: tuple[str, ...] = ("vcn", "nvenc", "qsv", "cpu")

# HandBrake announces hardware support in its startup banner on every
# invocation, e.g. "[17:01:27] vcn: is available". Unavailable families print
# "<name>: not available on this system", and a missing NVIDIA runtime prints
# "Cannot load nvEncodeAPI64.dll" with no family prefix at all — so we match
# only the positive form and treat absence as unavailable. That fails safe: at
# worst we under-report an encoder the user can still select by hand.
_AVAILABLE_RE = re.compile(
    r"^\s*(?:\[[\d:]+\]\s*)?(vcn|nvenc|qsv):\s*is available\s*$",
    re.MULTILINE | re.IGNORECASE,
)


@dataclass(frozen=True)
class Resolution:
    """The outcome of choosing presets for a job."""

    preset_1080: str
    preset_4k: str
    family: str            # the family actually used
    requested: str         # what was configured
    substituted: bool      # swapped away from a KNOWN-unavailable explicit family
    detection_unknown: bool  # capabilities could not be determined


def parse_capabilities(banner: str) -> set[str]:
    """Parse HandBrake's startup banner into the set of available families.

    ``cpu`` is always included: x265 is built into every HandBrake build. This
    means a successful parse never returns an empty set, which is what lets
    ``probe()`` use the empty set to mean "unknown" (see its docstring).
    """
    found = {m.group(1).lower() for m in _AVAILABLE_RE.finditer(banner or "")}
    found.add(CPU)
    return found


def _presets(family: str) -> tuple[str, str]:
    meta = FAMILIES[family]
    return meta["preset_1080"], meta["preset_4k"]


def resolve(
    family: str,
    available: set[str],
    *,
    fallback_cpu: bool = True,
    custom_1080: str = "",
    custom_4k: str = "",
) -> Resolution:
    """Pick the preset pair for a job.

    An EMPTY ``available`` means capabilities are unknown, which is deliberately
    not the same as "unavailable": an explicitly chosen family is always run as
    configured, so a broken probe can never silently divert the user onto an
    hours-long CPU encode.
    """
    unknown = not available

    if family == CUSTOM:
        return Resolution(custom_1080, custom_4k, CUSTOM, CUSTOM, False, unknown)

    if family == AUTO:
        if unknown:
            # Nothing to choose from. cpu is the only family guaranteed present
            # in any HandBrake build. In practice a failed probe means HandBrake
            # is missing or broken and the job fails regardless; this branch
            # exists for determinism, not rescue.
            p1080, p4k = _presets(CPU)
            return Resolution(p1080, p4k, CPU, AUTO, False, True)
        chosen = next(f for f in AUTO_PRIORITY if f in available)
        p1080, p4k = _presets(chosen)
        return Resolution(p1080, p4k, chosen, AUTO, False, False)

    if family not in FAMILIES:
        # Defensive: an unrecognised stored value behaves like custom.
        return Resolution(custom_1080, custom_4k, CUSTOM, family, False, unknown)

    if not unknown and family not in available and fallback_cpu:
        p1080, p4k = _presets(CPU)
        return Resolution(p1080, p4k, CPU, family, True, False)

    p1080, p4k = _presets(family)
    return Resolution(p1080, p4k, family, family, False, unknown)


def infer_family(preset_1080: str, preset_4k: str) -> str:
    """Reverse-map a stored preset pair onto a family, for read-time migration.

    Both presets must match the same family; a half-match is a hand-tuned setup
    and is preserved as ``custom``.
    """
    if not preset_1080 and not preset_4k:
        return AUTO
    for fid, meta in FAMILIES.items():
        if preset_1080 == meta["preset_1080"] and preset_4k == meta["preset_4k"]:
            return fid
    return CUSTOM
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_encoders.py -v`
Expected: PASS, 20 tests.

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/encoders.py tests/test_encoders.py
git commit -m "feat(encoders): add encoder family catalog, banner parser and preset resolution"
```

---

### Task 2: Capability probe (the subprocess boundary)

**Files:**
- Modify: `solution/transcoder/encoders.py` (append)
- Test: `tests/test_encoders_probe.py`

**Interfaces:**
- Consumes: `parse_capabilities` from Task 1.
- Produces: `probe(handbrake_cli: str, timeout: float = 30.0) -> set[str]` — returns the available set, or an **empty set** meaning "unknown".

- [ ] **Step 1: Write the failing tests**

Create `tests/test_encoders_probe.py`:

```python
import subprocess

import pytest

from transcoder import encoders
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
    assert probe("C:/HandBrake/HandBrakeCLI.exe") == {"vcn", CPU}
    assert captured["cmd"] == ["C:/HandBrake/HandBrakeCLI.exe", "--version"]
    # stderr must be folded into stdout: HandBrake writes the banner to stderr.
    assert captured["kwargs"]["stderr"] == subprocess.STDOUT


def test_probe_returns_empty_set_when_executable_is_missing(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe("nope.exe") == set()


def test_probe_returns_empty_set_on_timeout(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe("slow.exe") == set()


def test_probe_returns_empty_set_for_blank_path(monkeypatch):
    called = {"n": 0}

    def fake_run(cmd, **kwargs):
        called["n"] += 1
        return _Completed(AMD_BANNER)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe("") == set()
    assert called["n"] == 0  # must not shell out with an empty path


def test_probe_never_raises_on_unexpected_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe("x.exe") == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_encoders_probe.py -v`
Expected: FAIL — `ImportError: cannot import name 'probe'`

- [ ] **Step 3: Write the implementation**

Append to `solution/transcoder/encoders.py` (and add `import logging` and `import subprocess` to the imports at the top):

```python
log = logging.getLogger("transcoder")


def probe(handbrake_cli: str, timeout: float = 30.0) -> set[str]:
    """Ask HandBrake what it can encode with, by running ``--version``.

    HandBrake prints its capability banner on every invocation, so ``--version``
    is a ~1s probe. Returns the available families, or an EMPTY SET meaning
    "unknown" — a missing executable, a timeout, or any other failure. Callers
    must treat empty as unknown, never as "nothing available".
    """
    if not handbrake_cli:
        return set()
    try:
        # CREATE_NO_WINDOW keeps a console window from flashing when the app
        # runs from the tray or a scheduled task; absent on non-Windows.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            [handbrake_cli, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags,
        )
    except Exception as exc:  # missing exe, timeout, permission error, ...
        log.warning("Encoder probe failed for %r: %s", handbrake_cli, exc)
        return set()
    return parse_capabilities(proc.stdout or "")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_encoders_probe.py tests/test_encoders.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/encoders.py tests/test_encoders_probe.py
git commit -m "feat(encoders): add HandBrake capability probe with unknown-on-failure semantics"
```

---

### Task 3: Capability cache and job-time resolution (DB-aware)

**Files:**
- Modify: `solution/transcoder/encoders.py` (append)
- Modify: `solution/transcoder/config.py:26-27` (add `ENCODER_FAMILY`)
- Test: `tests/test_encoders_db.py`
- Test: `tests/test_config.py` (append one test)

**Interfaces:**
- Consumes: `probe`, `resolve`, `infer_family`, `Resolution` from Tasks 1-2; `get_setting`/`set_setting`/`get_effective` from `transcoder.repo`.
- Produces:
  - `CAPABILITIES_KEY = "encoder_capabilities"`
  - `load_capabilities(session) -> tuple[set[str], str | None]`
  - `store_capabilities(session, available: set[str]) -> str` (returns ISO timestamp; caller commits)
  - `detect_and_store(session, handbrake_cli: str) -> tuple[set[str], str | None]`
  - `get_or_detect_capabilities(session, handbrake_cli: str) -> tuple[set[str], str | None]`
  - `resolve_for_job(session) -> Resolution`
  - `migrate_encoder_family(session) -> str | None`
  - `settings.ENCODER_FAMILY: str = "auto"`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_encoders_db.py`:

```python
import json

from transcoder import encoders
from transcoder.encoders import (
    CAPABILITIES_KEY, CPU, AUTO, CUSTOM,
    detect_and_store, get_or_detect_capabilities, load_capabilities,
    migrate_encoder_family, resolve_for_job, store_capabilities,
)
from transcoder.repo import get_setting, set_setting


def test_load_capabilities_returns_unknown_when_absent(session):
    assert load_capabilities(session) == (set(), None)


def test_store_then_load_round_trips(session):
    stamp = store_capabilities(session, {"vcn", CPU})
    session.commit()
    available, detected_at = load_capabilities(session)
    assert available == {"vcn", CPU}
    assert detected_at == stamp


def test_load_capabilities_treats_corrupt_json_as_unknown(session):
    set_setting(session, CAPABILITIES_KEY, "not json{")
    session.commit()
    assert load_capabilities(session) == (set(), None)


def test_detect_and_store_persists_probe_result(session, monkeypatch):
    monkeypatch.setattr(encoders, "probe", lambda cli, **kw: {"vcn", CPU})
    available, detected_at = detect_and_store(session, "hb.exe")
    session.commit()
    assert available == {"vcn", CPU}
    assert detected_at is not None
    assert load_capabilities(session)[0] == {"vcn", CPU}


def test_detect_and_store_does_not_cache_a_failed_probe(session, monkeypatch):
    monkeypatch.setattr(encoders, "probe", lambda cli, **kw: set())
    available, detected_at = detect_and_store(session, "hb.exe")
    session.commit()
    assert available == set()
    assert detected_at is None
    assert get_setting(session, CAPABILITIES_KEY) is None


def test_get_or_detect_uses_cache_without_probing(session, monkeypatch):
    store_capabilities(session, {"nvenc", CPU})
    session.commit()

    def boom(*a, **k):
        raise AssertionError("probe must not run when a cache exists")

    monkeypatch.setattr(encoders, "probe", boom)
    assert get_or_detect_capabilities(session, "hb.exe")[0] == {"nvenc", CPU}


def test_get_or_detect_probes_once_and_caches_when_absent(session, monkeypatch):
    calls = {"n": 0}

    def fake_probe(cli, **kw):
        calls["n"] += 1
        return {"qsv", CPU}

    monkeypatch.setattr(encoders, "probe", fake_probe)
    assert get_or_detect_capabilities(session, "hb.exe")[0] == {"qsv", CPU}
    session.commit()
    assert get_or_detect_capabilities(session, "hb.exe")[0] == {"qsv", CPU}
    assert calls["n"] == 1


def test_resolve_for_job_uses_auto_and_cached_capabilities(session):
    set_setting(session, "encoder_family", AUTO)
    store_capabilities(session, {"vcn", CPU})
    session.commit()
    r = resolve_for_job(session)
    assert r.family == "vcn"
    assert r.preset_1080 == "H.265 VCN 1080p"


def test_resolve_for_job_falls_back_to_cpu_for_unavailable_family(session):
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "true")
    store_capabilities(session, {"vcn", CPU})
    session.commit()
    r = resolve_for_job(session)
    assert r.family == CPU
    assert r.requested == "nvenc"
    assert r.substituted is True


def test_resolve_for_job_honours_fallback_disabled(session):
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "false")
    store_capabilities(session, {"vcn", CPU})
    session.commit()
    r = resolve_for_job(session)
    assert r.family == "nvenc"
    assert r.substituted is False


def test_resolve_for_job_custom_uses_stored_preset_strings(session):
    set_setting(session, "encoder_family", CUSTOM)
    set_setting(session, "handbrake_preset_1080", "Mine 1080")
    set_setting(session, "handbrake_preset_4k", "Mine 4K")
    store_capabilities(session, {"vcn", CPU})
    session.commit()
    r = resolve_for_job(session)
    assert (r.preset_1080, r.preset_4k) == ("Mine 1080", "Mine 4K")


def test_migrate_marks_fresh_install_as_auto(session):
    # Fresh install: no presets have been seeded yet.
    assert migrate_encoder_family(session) == AUTO
    session.commit()
    assert get_setting(session, "encoder_family") == AUTO


def test_migrate_infers_family_from_existing_presets(session):
    set_setting(session, "handbrake_preset_1080", "H.265 NVENC 1080p")
    set_setting(session, "handbrake_preset_4k", "H.265 NVENC 2160p 4K")
    session.commit()
    assert migrate_encoder_family(session) == "nvenc"
    session.commit()
    assert get_setting(session, "encoder_family") == "nvenc"


def test_migrate_preserves_hand_tuned_presets_as_custom(session):
    set_setting(session, "handbrake_preset_1080", "Fast 1080p30")
    set_setting(session, "handbrake_preset_4k", "Fast 2160p60")
    session.commit()
    assert migrate_encoder_family(session) == CUSTOM


def test_migrate_is_idempotent_and_never_overwrites(session):
    set_setting(session, "encoder_family", "qsv")
    set_setting(session, "handbrake_preset_1080", "H.265 NVENC 1080p")
    session.commit()
    assert migrate_encoder_family(session) is None
    assert get_setting(session, "encoder_family") == "qsv"
```

Append to `tests/test_config.py`:

```python
def test_encoder_family_defaults_to_auto():
    from transcoder.config import settings
    assert settings.ENCODER_FAMILY == "auto"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_encoders_db.py tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'CAPABILITIES_KEY'`, plus the config test failing on a missing attribute.

- [ ] **Step 3: Write the implementation**

In `solution/transcoder/config.py`, add below `PRESET_4K` (line 27):

```python
    # Encoder family: auto | vcn | nvenc | qsv | cpu | custom. PRESET_1080/4K
    # above are only consulted in 'custom' mode; they are left at their historic
    # NVENC values so existing .env files keep their behaviour.
    ENCODER_FAMILY: str = "auto"
```

Append to `solution/transcoder/encoders.py` (add `import json` and `from datetime import datetime, timezone` to the imports):

```python
# ── DB-aware helpers ─────────────────────────────────────────────────────────
# These read and write the ordinary key/value `setting` table. Callers own the
# transaction boundary and must commit, matching the convention in repo.py.

CAPABILITIES_KEY = "encoder_capabilities"
FAMILY_KEY = "encoder_family"
FALLBACK_KEY = "encoder_fallback_cpu"


def load_capabilities(session) -> tuple[set[str], str | None]:
    """Read the cached probe result. Returns (set(), None) when unknown."""
    from transcoder.repo import get_setting

    raw = get_setting(session, CAPABILITIES_KEY)
    if not raw:
        return set(), None
    try:
        blob = json.loads(raw)
        return set(blob["available"]), blob.get("detected_at")
    except (ValueError, KeyError, TypeError):
        log.warning("Ignoring corrupt %s setting", CAPABILITIES_KEY)
        return set(), None


def store_capabilities(session, available: set[str]) -> str:
    """Cache a probe result; returns the ISO-8601 detection timestamp."""
    from transcoder.repo import set_setting

    detected_at = datetime.now(timezone.utc).isoformat()
    set_setting(session, CAPABILITIES_KEY, json.dumps({
        "available": sorted(available),
        "detected_at": detected_at,
    }))
    return detected_at


def detect_and_store(session, handbrake_cli: str) -> tuple[set[str], str | None]:
    """Probe and cache. A failed probe caches NOTHING, so 'unknown' never
    hardens into a stored 'nothing is available'."""
    available = probe(handbrake_cli)
    if not available:
        return set(), None
    return available, store_capabilities(session, available)


def get_or_detect_capabilities(session, handbrake_cli: str) -> tuple[set[str], str | None]:
    """Cached capabilities, probing once lazily if nothing is cached yet.

    This is what lets 'auto' work on a fresh install without adding a subprocess
    call to every server start.
    """
    available, detected_at = load_capabilities(session)
    if available:
        return available, detected_at
    return detect_and_store(session, handbrake_cli)


def resolve_for_job(session) -> Resolution:
    """Resolve the preset pair for a job from stored settings + capabilities."""
    from transcoder.config import settings as cfg
    from transcoder.repo import get_effective

    family = get_effective(session, FAMILY_KEY, cfg.ENCODER_FAMILY)
    fallback = get_effective(session, FALLBACK_KEY, "true") == "true"
    custom_1080 = get_effective(session, "handbrake_preset_1080", cfg.PRESET_1080)
    custom_4k = get_effective(session, "handbrake_preset_4k", cfg.PRESET_4K)
    handbrake_cli = get_effective(session, "handbrake_cli", cfg.HANDBRAKE_CLI)

    available, _ = get_or_detect_capabilities(session, handbrake_cli)
    return resolve(
        family, available,
        fallback_cpu=fallback,
        custom_1080=custom_1080,
        custom_4k=custom_4k,
    )


def migrate_encoder_family(session) -> str | None:
    """One-time backfill of `encoder_family`. Returns the value written, or None
    if it was already set. Caller commits.

    MUST run BEFORE seed_settings_from_env(): that seeder writes the NVENC
    config defaults into `handbrake_preset_1080`/`_4k` on every startup, so once
    it has run there is no way to tell a fresh install from a deliberate NVIDIA
    setup. The presence of `handbrake_preset_1080` in the DB is therefore the
    signal for "this install predates encoder families".
    """
    from transcoder.repo import get_setting, set_setting

    if get_setting(session, FAMILY_KEY) is not None:
        return None

    stored_1080 = get_setting(session, "handbrake_preset_1080")
    if stored_1080 is None:
        value = AUTO  # fresh install: nothing seeded yet
    else:
        value = infer_family(stored_1080, get_setting(session, "handbrake_preset_4k") or "")
    set_setting(session, FAMILY_KEY, value)
    log.info("Backfilled encoder_family=%s", value)
    return value
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_encoders_db.py tests/test_config.py tests/test_encoders.py tests/test_encoders_probe.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/encoders.py solution/transcoder/config.py tests/test_encoders_db.py tests/test_config.py
git commit -m "feat(encoders): add capability cache, job resolution and encoder_family backfill"
```

---

### Task 4: Wire the migration into startup

Runs the backfill before the seeder, which is the only ordering that produces correct results.

**Files:**
- Modify: `solution/transcoder/api/app.py:50-58` (inside the lifespan, before `seed_settings_from_env`)
- Test: `tests/test_api_encoder_migration.py`

**Interfaces:**
- Consumes: `migrate_encoder_family` from Task 3.
- Produces: nothing new; guarantees `encoder_family` is set after first boot.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_encoder_migration.py`:

```python
from transcoder.repo import get_setting


def test_fresh_install_boots_with_encoder_family_auto(api):
    _client, Session = api
    with Session() as db:
        assert get_setting(db, "encoder_family") == "auto"


def test_migration_runs_before_preset_seeding(api):
    """The seeder writes NVENC defaults on every boot. If the backfill ran after
    it, a fresh install would be misread as a deliberate NVIDIA setup."""
    _client, Session = api
    with Session() as db:
        assert get_setting(db, "handbrake_preset_1080") == "H.265 NVENC 1080p"
        assert get_setting(db, "encoder_family") == "auto"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_api_encoder_migration.py -v`
Expected: FAIL — `assert None == 'auto'`

- [ ] **Step 3: Write the implementation**

In `solution/transcoder/api/app.py`, inside the lifespan's `with _SL() as _db:` block, insert the backfill **immediately before** the `seed_settings_from_env(...)` call:

```python
        with _SL() as _db:
            # MUST precede seed_settings_from_env: the seeder writes the NVENC
            # preset defaults, after which a fresh install is indistinguishable
            # from a deliberate NVIDIA setup.
            from transcoder.encoders import migrate_encoder_family
            if migrate_encoder_family(_db) is not None:
                _db.commit()
            seed_settings_from_env(_db, {
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_api_encoder_migration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/api/app.py tests/test_api_encoder_migration.py
git commit -m "feat(encoders): backfill encoder_family at startup before preset seeding"
```

---

### Task 5: Worker uses resolved presets and logs substitutions

**Files:**
- Modify: `solution/transcoder/engine/worker.py:85-87` and the transcode log line (~112)
- Modify: `tests/conftest.py` (add an autouse probe stub)
- Modify: `tests/test_worker.py:87` (one assertion — see Step 4)
- Test: `tests/test_worker_encoder.py`

**Interfaces:**
- Consumes: `resolve_for_job` from Task 3, `FAMILIES` from Task 1, `job_log` from `worker.py:35`.
- Reuses from `tests/test_worker.py`: `FakeClient`, `_item(session, **kw)`, and
  `_make_io(smaller=True, fail=False, fail_download=False)` which returns the 4-tuple
  `(calls, download, upload, convert)`.
- Produces: no new public names; `job.preset` now comes from the resolver.

- [ ] **Step 1: Add an autouse probe stub so tests never shell out**

`resolve_for_job` lazily probes when nothing is cached. Without this, every existing
worker test would launch a real `HandBrakeCLI` subprocess — slow, and passing or failing
depending on whether the developer happens to have it on PATH.

Append to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _no_encoder_probe(monkeypatch):
    """Keep tests hermetic: never shell out to a real HandBrakeCLI.

    Returns the empty set, i.e. "capabilities unknown". Tests that care about
    specific hardware seed the cache with encoders.store_capabilities() or
    monkeypatch encoders.probe themselves, which overrides this.
    """
    try:
        from transcoder import encoders
    except ImportError:
        return  # module does not exist yet in earlier tasks
    monkeypatch.setattr(encoders, "probe", lambda *a, **k: set())
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_worker_encoder.py`:

```python
import os

from transcoder import encoders
from transcoder.encoders import CPU
from transcoder.engine.worker import process_one_job
from transcoder.models import Job
from transcoder.repo import set_setting

from tests.test_worker import FakeClient, _item, _make_io


def _patch_fs(monkeypatch):
    """Same filesystem stubs the existing worker tests use."""
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000 if "tmp" in p else 400)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)


def _job(session, item):
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()
    return job


def _run(session, job, **io_kw):
    _calls, download, upload, convert = _make_io(**io_kw)
    process_one_job(session, job, {"sonarr": FakeClient()},
                    download=download, upload=upload, convert=convert)


def test_worker_uses_auto_resolved_amd_preset(session, monkeypatch):
    _patch_fs(monkeypatch)
    item = _item(session, resolution=1080)
    job = _job(session, item)
    set_setting(session, "encoder_family", "auto")
    encoders.store_capabilities(session, {"vcn", CPU})
    session.commit()

    _run(session, job)
    assert job.preset == "H.265 VCN 1080p"


def test_worker_picks_4k_preset_for_high_resolution(session, monkeypatch):
    _patch_fs(monkeypatch)
    item = _item(session, resolution=2160)
    job = _job(session, item)
    set_setting(session, "encoder_family", "auto")
    encoders.store_capabilities(session, {"vcn", CPU})
    session.commit()

    _run(session, job)
    assert job.preset == "H.265 VCN 2160p 4K"


def test_worker_falls_back_to_cpu_and_logs_loudly(session, monkeypatch):
    _patch_fs(monkeypatch)
    item = _item(session, resolution=1080)
    job = _job(session, item)
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "true")
    encoders.store_capabilities(session, {"vcn", CPU})
    session.commit()

    _run(session, job)
    assert job.preset == "H.265 MKV 1080p30"
    assert "NVIDIA NVENC" in job.log
    assert "slower" in job.log.lower()


def test_worker_does_not_fall_back_when_capabilities_unknown(session, monkeypatch):
    """Unknown is not unavailable: a failed probe must not override the choice."""
    _patch_fs(monkeypatch)
    item = _item(session, resolution=1080)
    job = _job(session, item)
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "true")
    session.commit()  # nothing cached; the autouse stub makes probe return unknown

    _run(session, job)
    assert job.preset == "H.265 NVENC 1080p"


def test_generic_handbrake_failure_does_not_trigger_cpu_fallback(session, monkeypatch):
    """A corrupt input must never silently start an hours-long CPU encode."""
    _patch_fs(monkeypatch)
    item = _item(session, resolution=1080)
    job = _job(session, item)
    set_setting(session, "encoder_family", "vcn")
    encoders.store_capabilities(session, {"vcn", CPU})
    session.commit()

    _run(session, job, fail=True)
    assert job.state == "failed"
    assert job.preset == "H.265 VCN 1080p"
    assert "MKV" not in (job.log or "")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_worker_encoder.py -v`
Expected: FAIL — the worker still reads raw preset settings, so `job.preset` is `H.265 NVENC 1080p`.

- [ ] **Step 4: Write the implementation**

In `solution/transcoder/engine/worker.py`, replace lines 85-87:

```python
        preset_4k = get_effective(session, "handbrake_preset_4k", settings.PRESET_4K)
        preset_1080 = get_effective(session, "handbrake_preset_1080", settings.PRESET_1080)
        job.preset = preset_4k if item.resolution > 1080 else preset_1080
```

with:

```python
        resolution = resolve_for_job(session)
        job.preset = (
            resolution.preset_4k if item.resolution > 1080 else resolution.preset_1080
        )
```

Add to the imports at the top of `worker.py`:

```python
from transcoder.encoders import FAMILIES, resolve_for_job
```

Then, immediately after the existing transcode log line (~112):

```python
        job_log(session, job, f"Transcoding {item.title} (preset {job.preset})")
```

insert:

```python
        if resolution.substituted:
            requested = FAMILIES[resolution.requested]["label"]
            job_log(
                session, job,
                f"{requested} is not available on this host; falling back to "
                "CPU x265 — this will be substantially slower",
            )
        elif resolution.detection_unknown:
            job_log(
                session, job,
                "Encoder detection unavailable; running the configured preset as set",
            )
```

- [ ] **Step 5: Update the one existing assertion this changes**

`tests/test_worker.py:87` currently asserts the hardcoded NVENC preset:

```python
    assert job.preset == "H.265 NVENC 1080p"
```

That test seeds no encoder settings, so it now resolves `auto` against unknown
capabilities (the autouse stub from Step 1) and correctly lands on CPU x265. Change it to:

```python
    # No encoder settings seeded: 'auto' with unknown capabilities resolves to
    # CPU x265, the only family guaranteed present in any HandBrake build.
    assert job.preset == "H.265 MKV 1080p30"
```

Do not change any other assertion in that file. If a different test also fails, stop and
re-read it rather than editing assertions to fit.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_worker_encoder.py tests/test_worker.py tests/test_worker_cancel.py tests/test_worker_logs.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add solution/transcoder/engine/worker.py tests/test_worker_encoder.py tests/test_worker.py tests/conftest.py
git commit -m "feat(worker): resolve presets by encoder family with logged CPU fallback"
```

---

### Task 6: Settings API exposes encoder_family and encoder_fallback_cpu

**Files:**
- Modify: `solution/transcoder/api/schemas.py:157-158` (SettingsOut) and `:176-177` (SettingsUpdate)
- Modify: `solution/transcoder/api/routers/settings.py:43-44` (read) and `:73` (simple_fields)
- Test: `tests/test_api_settings_encoder.py`

**Interfaces:**
- Consumes: `encoders.FAMILY_KEY`, `encoders.FALLBACK_KEY` from Task 3.
- Produces: `SettingsOut.encoder_family: str`, `SettingsOut.encoder_fallback_cpu: str`, and the matching optional fields on `SettingsUpdate`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_settings_encoder.py`:

```python
from transcoder.repo import get_setting


def test_settings_exposes_encoder_family_and_fallback(api):
    client, _Session = api
    body = client.get("/api/settings").json()
    assert body["encoder_family"] == "auto"
    assert body["encoder_fallback_cpu"] == "true"


def test_settings_update_persists_encoder_family(api):
    client, Session = api
    r = client.put("/api/settings", json={"encoder_family": "vcn"})
    assert r.status_code == 200
    assert "encoder_family" in r.json()["updated"]
    with Session() as db:
        assert get_setting(db, "encoder_family") == "vcn"


def test_settings_update_can_disable_cpu_fallback(api):
    client, Session = api
    client.put("/api/settings", json={"encoder_fallback_cpu": "false"})
    with Session() as db:
        assert get_setting(db, "encoder_fallback_cpu") == "false"
    assert client.get("/api/settings").json()["encoder_fallback_cpu"] == "false"


def test_custom_family_keeps_free_text_presets_editable(api):
    client, Session = api
    client.put("/api/settings", json={
        "encoder_family": "custom",
        "handbrake_preset_1080": "Mine 1080",
        "handbrake_preset_4k": "Mine 4K",
    })
    body = client.get("/api/settings").json()
    assert body["encoder_family"] == "custom"
    assert body["handbrake_preset_1080"] == "Mine 1080"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_api_settings_encoder.py -v`
Expected: FAIL — `KeyError: 'encoder_family'`

- [ ] **Step 3: Write the implementation**

In `solution/transcoder/api/schemas.py`, add to `SettingsOut` after `handbrake_preset_4k` (line 158):

```python
    encoder_family: str = "auto"
    encoder_fallback_cpu: str = "true"
```

and to `SettingsUpdate` after its `handbrake_preset_4k` (line 177):

```python
    encoder_family: str | None = None
    encoder_fallback_cpu: str | None = None
```

In `solution/transcoder/api/routers/settings.py`, add to the `SettingsOut(...)` construction after `handbrake_preset_4k` (line 44):

```python
        encoder_family=get_effective(db, "encoder_family", cfg.ENCODER_FAMILY),
        encoder_fallback_cpu=get_effective(db, "encoder_fallback_cpu", "true"),
```

and extend `simple_fields` (line 73) to include the two new keys:

```python
        "handbrake_cli", "handbrake_preset_1080", "handbrake_preset_4k",
        "encoder_family", "encoder_fallback_cpu",
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_api_settings_encoder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/api/schemas.py solution/transcoder/api/routers/settings.py tests/test_api_settings_encoder.py
git commit -m "feat(api): expose encoder_family and encoder_fallback_cpu in settings"
```

---

### Task 7: `/api/encoders` and `/api/encoders/detect`

**Files:**
- Create: `solution/transcoder/api/routers/encoders.py`
- Modify: `solution/transcoder/api/app.py:106-115` (register the router)
- Test: `tests/test_api_encoders.py`

**Interfaces:**
- Consumes: `encoders.FAMILIES`, `load_capabilities`, `detect_and_store` from Tasks 1-3.
- Produces: `GET /api/encoders` and `POST /api/encoders/detect`, both returning
  `{"available": [...], "detected_at": str|None, "families": [{"id", "label", "preset_1080", "preset_4k", "hardware", "available"}]}`; detect adds `"ok": bool` and, on failure, `"error": str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_encoders.py`:

```python
from transcoder import encoders
from transcoder.encoders import CPU
from transcoder.repo import get_setting, set_setting


def test_encoders_requires_auth(api):
    client, _Session = api
    client.post("/api/logout")
    assert client.get("/api/encoders").status_code in (401, 403)


def test_get_encoders_lists_the_catalog(api):
    client, _Session = api
    body = client.get("/api/encoders").json()
    ids = [f["id"] for f in body["families"]]
    assert ids == ["vcn", "nvenc", "qsv", "cpu"]
    assert "mf" not in ids
    vcn = next(f for f in body["families"] if f["id"] == "vcn")
    assert vcn["preset_1080"] == "H.265 VCN 1080p"
    assert vcn["hardware"] is True


def test_get_encoders_reports_unknown_before_detection(api):
    client, Session = api
    with Session() as db:
        assert get_setting(db, encoders.CAPABILITIES_KEY) is None
    body = client.get("/api/encoders").json()
    assert body["available"] == []
    assert body["detected_at"] is None
    assert all(f["available"] is False for f in body["families"])


def test_get_encoders_does_not_probe(api, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("GET must never shell out")

    monkeypatch.setattr(encoders, "probe", boom)
    assert api[0].get("/api/encoders").status_code == 200


def test_detect_probes_caches_and_reports(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(encoders, "probe", lambda cli, **kw: {"vcn", CPU})
    with Session() as db:
        set_setting(db, "handbrake_cli", "hb.exe")
        db.commit()

    body = client.post("/api/encoders/detect", json={}).json()
    assert body["ok"] is True
    assert sorted(body["available"]) == ["cpu", "vcn"]
    assert body["detected_at"] is not None
    # cached for the next GET
    assert sorted(client.get("/api/encoders").json()["available"]) == ["cpu", "vcn"]


def test_detect_accepts_an_unsaved_cli_path(api, monkeypatch):
    client, _Session = api
    seen = {}

    def fake_probe(cli, **kw):
        seen["cli"] = cli
        return {"qsv", CPU}

    monkeypatch.setattr(encoders, "probe", fake_probe)
    client.post("/api/encoders/detect", json={"handbrake_cli": "D:/typed.exe"})
    assert seen["cli"] == "D:/typed.exe"


def test_detect_reports_failure_without_caching(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(encoders, "probe", lambda cli, **kw: set())
    with Session() as db:
        set_setting(db, "handbrake_cli", "broken.exe")
        db.commit()

    body = client.post("/api/encoders/detect", json={}).json()
    assert body["ok"] is False
    assert "broken.exe" in body["error"]
    with Session() as db:
        assert get_setting(db, encoders.CAPABILITIES_KEY) is None


def test_detect_errors_when_no_cli_configured(api, monkeypatch):
    client, Session = api
    with Session() as db:
        set_setting(db, "handbrake_cli", "")
        db.commit()
    monkeypatch.setattr(encoders, "probe", lambda cli, **kw: {"vcn", CPU})
    body = client.post("/api/encoders/detect", json={}).json()
    assert body["ok"] is False
    assert "not set" in body["error"].lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_api_encoders.py -v`
Expected: FAIL — 404 on both routes.

- [ ] **Step 3: Write the implementation**

Create `solution/transcoder/api/routers/encoders.py`:

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from transcoder import config as _cfg
from transcoder import encoders
from transcoder.api.deps import get_session as get_db
from transcoder.repo import get_effective

router = APIRouter(prefix="/api/encoders", tags=["encoders"])


class DetectBody(BaseModel):
    # Lets the setup wizard detect against a path the user has typed but not
    # yet saved, mirroring POST /api/settings/test/{service}.
    handbrake_cli: str | None = None


def _payload(available: set[str], detected_at: str | None) -> dict:
    return {
        "available": sorted(available),
        "detected_at": detected_at,
        "families": [
            {
                "id": fid,
                "label": meta["label"],
                "preset_1080": meta["preset_1080"],
                "preset_4k": meta["preset_4k"],
                "hardware": meta["hardware"],
                "available": fid in available,
            }
            for fid, meta in encoders.FAMILIES.items()
        ],
    }


@router.get("")
def list_encoders(db: Session = Depends(get_db)):
    """Catalog plus cached availability. Never shells out."""
    available, detected_at = encoders.load_capabilities(db)
    return _payload(available, detected_at)


@router.post("/detect")
def detect(body: DetectBody, db: Session = Depends(get_db)):
    """Probe HandBrake and cache the result."""
    cli = body.handbrake_cli or get_effective(db, "handbrake_cli", _cfg.settings.HANDBRAKE_CLI)
    if not cli:
        return {"ok": False, "error": "HandBrake CLI path is not set", **_payload(set(), None)}

    available, detected_at = encoders.detect_and_store(db, cli)
    if not available:
        return {
            "ok": False,
            "error": f"Could not run {cli}. Check the HandBrake CLI path.",
            **_payload(set(), None),
        }
    db.commit()
    return {"ok": True, **_payload(available, detected_at)}
```

In `solution/transcoder/api/app.py`, extend the protected router import and registration (lines 106-115):

```python
    from transcoder.api.routers import library, scan, jobs, exclusions, stream, logs, backup, encoders
```

and add alongside the other `include_router` calls:

```python
    app.include_router(encoders.router, dependencies=protected)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_api_encoders.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/api/routers/encoders.py solution/transcoder/api/app.py tests/test_api_encoders.py
git commit -m "feat(api): add GET /api/encoders and POST /api/encoders/detect"
```

---

### Task 8: Frontend types, API client, and a Select primitive

**Files:**
- Create: `solution/web/src/components/ui/select.tsx`
- Modify: `solution/web/src/api/types.ts:48-49` (Settings) and `:67-68` (SettingsUpdate)
- Modify: `solution/web/src/api/client.ts` (append two functions)
- Test: `solution/web/src/components/ui/ui.test.tsx` (append)

**Interfaces:**
- Consumes: the JSON shape from Task 7.
- Produces:
  - `Select` component (native `<select>` styled to match `Input`)
  - `EncoderFamily`, `EncodersResponse`, `DetectResponse` types
  - `getEncoders(): Promise<EncodersResponse>`
  - `detectEncoders(handbrakeCli?: string): Promise<DetectResponse>`
  - `Settings.encoder_family`, `Settings.encoder_fallback_cpu`

- [ ] **Step 1: Write the failing test**

Append to `solution/web/src/components/ui/ui.test.tsx`:

```tsx
import { Select } from "./select";

test("Select renders options and reports changes", () => {
  const onChange = vi.fn();
  render(
    <Select aria-label="Encoder" value="vcn" onChange={onChange}>
      <option value="vcn">AMD VCN</option>
      <option value="cpu">CPU (x265)</option>
    </Select>,
  );
  const el = screen.getByLabelText("Encoder") as HTMLSelectElement;
  expect(el.value).toBe("vcn");
  fireEvent.change(el, { target: { value: "cpu" } });
  expect(onChange).toHaveBeenCalled();
});
```

> If `ui.test.tsx` does not already import `render`, `screen`, `fireEvent`, `vi` and `test`,
> add them to its existing imports rather than duplicating import statements.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd solution/web && npm test -- ui.test`
Expected: FAIL — cannot resolve `./select`.

- [ ] **Step 3: Write the implementation**

Create `solution/web/src/components/ui/select.tsx`:

```tsx
import { forwardRef, SelectHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <select
        ref={ref}
        className={cn(
          "h-9 rounded-md border border-border bg-elevated px-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent/50 disabled:opacity-50 disabled:cursor-not-allowed",
          className
        )}
        {...props}
      >
        {children}
      </select>
    );
  }
);

Select.displayName = "Select";
```

Add to `solution/web/src/api/types.ts` — inside `Settings` after `handbrake_preset_4k` (line 49):

```ts
  encoder_family: string;
  encoder_fallback_cpu: string;
```

inside `SettingsUpdate` after its `handbrake_preset_4k` (line 68):

```ts
  encoder_family?: string;
  encoder_fallback_cpu?: string;
```

and at the end of the file:

```ts
export interface EncoderFamily {
  id: string;
  label: string;
  preset_1080: string;
  preset_4k: string;
  hardware: boolean;
  available: boolean;
}

export interface EncodersResponse {
  available: string[];
  detected_at: string | null;
  families: EncoderFamily[];
}

export interface DetectResponse extends EncodersResponse {
  ok: boolean;
  error?: string;
}
```

Append to `solution/web/src/api/client.ts`:

```ts
import type { EncodersResponse, DetectResponse } from './types';

export const getEncoders = (): Promise<EncodersResponse> =>
  api.get<EncodersResponse>('/api/encoders');

export const detectEncoders = (handbrakeCli?: string): Promise<DetectResponse> =>
  api.post<DetectResponse>('/api/encoders/detect', { handbrake_cli: handbrakeCli || null });
```

> Merge the `import type` line into the file's existing `import type { ... } from './types'`
> statement rather than adding a second one.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd solution/web && npm test -- ui.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solution/web/src/components/ui/select.tsx solution/web/src/components/ui/ui.test.tsx solution/web/src/api/types.ts solution/web/src/api/client.ts
git commit -m "feat(web): add Select primitive and encoder API client types"
```

---

### Task 9: Settings page Encoder section

**Files:**
- Modify: `solution/web/src/pages/Settings.tsx` — imports, state, the `useEffect` hydrate block (~line 212), and the Encoder section (lines 430-467)
- Test: `solution/web/src/pages/Settings.test.tsx`

**Interfaces:**
- Consumes: `Select`, `getEncoders`, `detectEncoders`, `EncodersResponse` from Task 8; the settings fields from Task 6.
- Produces: no exports; UI only.

- [ ] **Step 1: Write the failing tests**

Append to `solution/web/src/pages/Settings.test.tsx`. Add `encoder_family: "auto"` and `encoder_fallback_cpu: "true"` to the existing `SETTINGS` fixture, extend `makeFetch` to answer the encoder routes, then:

```tsx
test("encoder dropdown shows the family choices", async () => {
  vi.stubGlobal("fetch", makeFetch({}));
  renderPage();
  const sel = await screen.findByLabelText(/^encoder$/i);
  expect(sel).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /amd vcn/i })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /cpu \(x265\)/i })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /custom/i })).toBeInTheDocument();
});

test("preset fields are hidden unless Custom is selected", async () => {
  vi.stubGlobal("fetch", makeFetch({}));
  renderPage();
  const sel = await screen.findByLabelText(/^encoder$/i);
  expect(screen.queryByLabelText(/1080p preset/i)).not.toBeInTheDocument();
  fireEvent.change(sel, { target: { value: "custom" } });
  expect(screen.getByLabelText(/1080p preset/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/4k preset/i)).toBeInTheDocument();
});

test("saving the encoder section sends the family and fallback flag", async () => {
  const captured: { body?: string } = {};
  vi.stubGlobal("fetch", makeFetch(captured));
  renderPage();
  const sel = await screen.findByLabelText(/^encoder$/i);
  fireEvent.change(sel, { target: { value: "vcn" } });
  fireEvent.click(screen.getByRole("button", { name: /save encoder settings/i }));
  await waitFor(() => expect(captured.body).toBeTruthy());
  const body = JSON.parse(captured.body!);
  expect(body.encoder_family).toBe("vcn");
  expect(body.encoder_fallback_cpu).toBe("true");
});

test("no availability badges are shown before detection has run", async () => {
  // Unknown is not unavailable: don't label everything "not available" just
  // because nobody has clicked Detect yet.
  vi.stubGlobal("fetch", makeFetch({}));
  renderPage();
  await screen.findByLabelText(/^encoder$/i);
  expect(screen.queryByTestId("enc-avail-vcn")).not.toBeInTheDocument();
});

test("detect shows availability badges", async () => {
  vi.stubGlobal("fetch", makeFetch({}));
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: /detect/i }));
  // Assert on the badges by test id: the family label also appears as an
  // <option> in the dropdown, so a text query would match twice.
  await waitFor(() =>
    expect(screen.getByTestId("enc-avail-vcn")).toHaveTextContent(/AMD VCN: available/i),
  );
  expect(screen.getByTestId("enc-avail-nvenc")).toHaveTextContent(/not available/i);
});

test("warns when the chosen family is known to be unavailable", async () => {
  vi.stubGlobal("fetch", makeFetch({}));
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: /detect/i }));
  const sel = await screen.findByLabelText(/^encoder$/i);
  fireEvent.change(sel, { target: { value: "nvenc" } });
  expect(await screen.findByRole("alert")).toHaveTextContent(/not available/i);
});
```

Extend `makeFetch` with:

```tsx
    if (url.includes("/api/encoders/detect")) {
      return new Response(JSON.stringify({
        ok: true, available: ["cpu", "vcn"], detected_at: "2026-09-05T17:00:00Z",
        families: ENCODER_FAMILIES,
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (url.includes("/api/encoders")) {
      return new Response(JSON.stringify({
        available: [], detected_at: null,
        families: ENCODER_FAMILIES.map(f => ({ ...f, available: false })),
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
```

and define above it:

```tsx
const ENCODER_FAMILIES = [
  { id: "vcn", label: "AMD VCN", preset_1080: "H.265 VCN 1080p", preset_4k: "H.265 VCN 2160p 4K", hardware: true, available: true },
  { id: "nvenc", label: "NVIDIA NVENC", preset_1080: "H.265 NVENC 1080p", preset_4k: "H.265 NVENC 2160p 4K", hardware: true, available: false },
  { id: "qsv", label: "Intel QSV", preset_1080: "H.265 QSV 1080p", preset_4k: "H.265 QSV 2160p 4K", hardware: true, available: false },
  { id: "cpu", label: "CPU (x265)", preset_1080: "H.265 MKV 1080p30", preset_4k: "H.265 MKV 2160p60 4K", hardware: false, available: true },
];
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd solution/web && npm test -- Settings`
Expected: FAIL — no element labelled "Encoder".

- [ ] **Step 3: Write the implementation**

In `solution/web/src/pages/Settings.tsx`:

Add imports:

```tsx
import { Select } from '../components/ui/select';
import { Badge } from '../components/ui/badge';
import { getEncoders, detectEncoders } from '../api/client';
import type { EncodersResponse } from '../api/types';
```

Add state beside the existing encoder state:

```tsx
  const [encFamily, setEncFamily] = useState('auto');
  const [encFallback, setEncFallback] = useState(true);
  const [encInfo, setEncInfo] = useState<EncodersResponse | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [detectError, setDetectError] = useState<string | null>(null);
```

Load the catalog once:

```tsx
  const { data: encoderData } = useQuery({ queryKey: ['encoders'], queryFn: getEncoders });
  useEffect(() => { if (encoderData) setEncInfo(encoderData); }, [encoderData]);
```

In the hydrate `useEffect` (after line 213):

```tsx
    setEncFamily(data.encoder_family || 'auto');
    setEncFallback(data.encoder_fallback_cpu !== 'false');
```

Add the detect handler:

```tsx
  async function runDetect() {
    setDetecting(true);
    setDetectError(null);
    try {
      const res = await detectEncoders(hbCli);
      setEncInfo(res);
      if (!res.ok) setDetectError(res.error ?? 'Detection failed');
    } catch {
      setDetectError('Detection failed');
    } finally {
      setDetecting(false);
    }
  }

  // Only warn when detection actually ran: unknown is not unavailable.
  const detected = !!encInfo?.detected_at;
  const chosen = encInfo?.families.find(f => f.id === encFamily);
  const familyUnavailable = detected && !!chosen && !chosen.available;
```

Replace the two preset `Field`s in the Encoder section (lines 444-450) with:

```tsx
            <Field htmlFor="enc-family" label="Encoder">
              <Select id="enc-family" value={encFamily}
                onChange={e => { setEncFamily(e.target.value); setTransDirty(true); }}>
                <option value="auto">Auto (recommended)</option>
                {(encInfo?.families ?? []).map(f => (
                  <option key={f.id} value={f.id}>{f.label}</option>
                ))}
                <option value="custom">Custom…</option>
              </Select>
            </Field>

            <div className="flex items-center gap-3">
              <Button size="sm" variant="outline" onClick={runDetect} disabled={detecting}
                aria-busy={detecting} aria-label="Detect available encoders">
                {detecting ? 'Detecting…' : 'Detect'}
              </Button>
              {/* Only after a real probe — an undetected host is unknown, not empty. */}
              {detected && encInfo?.families.map(f => (
                <Badge key={f.id} data-testid={`enc-avail-${f.id}`}
                  variant={f.available ? 'done' : 'neutral'}>
                  {f.label}: {f.available ? 'available' : 'not available'}
                </Badge>
              ))}
            </div>
            {detectError && (
              <p className="text-xs text-state-failed">{detectError}</p>
            )}
            {familyUnavailable && (
              <p role="alert" className="text-xs text-state-failed">
                {chosen?.label} is not available on this host.
                {encFallback
                  ? ' Jobs will fall back to CPU x265, which is substantially slower.'
                  : ' Jobs using it will fail.'}
              </p>
            )}

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={encFallback}
                onChange={e => { setEncFallback(e.target.checked); setTransDirty(true); }} />
              Fall back to CPU x265 when the hardware encoder is unavailable
            </label>

            {encFamily === 'custom' && (
              <>
                <Field htmlFor="hb-1080" label="1080p preset">
                  <Input id="hb-1080" value={hbPreset1080}
                    onChange={e => { setHbPreset1080(e.target.value); setTransDirty(true); }} />
                </Field>
                <Field htmlFor="hb-4k" label="4K preset">
                  <Input id="hb-4k" value={hbPreset4k}
                    onChange={e => { setHbPreset4k(e.target.value); setTransDirty(true); }} />
                </Field>
              </>
            )}
```

Update the section's Save payload (lines 456-457):

```tsx
                  { handbrake_cli: hbCli,
                    encoder_family: encFamily,
                    encoder_fallback_cpu: encFallback ? 'true' : 'false',
                    ...(encFamily === 'custom'
                      ? { handbrake_preset_1080: hbPreset1080, handbrake_preset_4k: hbPreset4k }
                      : {}) },
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd solution/web && npm test -- Settings`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solution/web/src/pages/Settings.tsx solution/web/src/pages/Settings.test.tsx
git commit -m "feat(web): encoder family selector with detection in Settings"
```

---

### Task 10: Setup wizard detection step

**Files:**
- Modify: `solution/web/src/pages/Setup.tsx:12-28` (state) and `:117-128` (handbrake step) and `saveHandbrake` (`:58-66`)
- Test: `solution/web/src/pages/Setup.test.tsx`

**Interfaces:**
- Consumes: `detectEncoders` from Task 8; `updateSettings` already imported by `Setup.tsx`.
- Produces: no exports; the wizard now writes `encoder_family` alongside `handbrake_cli`.

- [ ] **Step 1: Write the failing tests**

Append to `solution/web/src/pages/Setup.test.tsx`. The file already imports `render`,
`screen`, `waitFor`, `userEvent`, `afterEach`, `expect`, `test` and `vi` — reuse those and
do not add a `fireEvent` import.

```tsx
const DETECT_OK = {
  ok: true,
  available: ["cpu", "vcn"],
  detected_at: "2026-09-05T17:00:00Z",
  families: [
    { id: "vcn", label: "AMD VCN", preset_1080: "H.265 VCN 1080p", preset_4k: "H.265 VCN 2160p 4K", hardware: true, available: true },
    { id: "cpu", label: "CPU (x265)", preset_1080: "H.265 MKV 1080p30", preset_4k: "H.265 MKV 2160p60 4K", hardware: false, available: true },
  ],
};

const DETECT_FAIL = {
  ok: false,
  error: "Could not run hb.exe. Check the HandBrake CLI path.",
  available: [],
  detected_at: null,
  families: [],
};

function stubFetch(detectBody: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const body = url.includes("/api/encoders/detect") ? detectBody : { ok: true };
    return new Response(JSON.stringify(body), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }));
}

/** Render the wizard and advance password -> connections -> handbrake step. */
async function gotoHandbrakeStep() {
  render(<Setup onDone={() => {}} />);
  await userEvent.type(screen.getByLabelText(/password/i), "hunter2");
  await userEvent.click(screen.getByRole("button", { name: /create password/i }));
  // Skip connections; the next screen is the HandBrake step.
  await userEvent.click(await screen.findByRole("button", { name: /skip/i }));
}

test("wizard detects encoders and reports the hardware found", async () => {
  stubFetch(DETECT_OK);
  await gotoHandbrakeStep();
  await userEvent.click(await screen.findByRole("button", { name: /detect/i }));
  expect(await screen.findByText(/Found AMD VCN/i)).toBeInTheDocument();
});

test("wizard reports when detection fails", async () => {
  stubFetch(DETECT_FAIL);
  await gotoHandbrakeStep();
  await userEvent.click(await screen.findByRole("button", { name: /detect/i }));
  expect(await screen.findByText(/could not run/i)).toBeInTheDocument();
});

test("wizard saves the detected family with the CLI path", async () => {
  stubFetch(DETECT_OK);
  await gotoHandbrakeStep();
  await userEvent.click(await screen.findByRole("button", { name: /detect/i }));
  await screen.findByText(/Found AMD VCN/i);
  await userEvent.click(screen.getByRole("button", { name: /save & continue/i }));

  await waitFor(() => {
    const put = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (c) => String(c[0]).includes("/api/settings"),
    );
    expect(put).toBeTruthy();
    expect(JSON.parse((put![1] as RequestInit).body as string).encoder_family).toBe("vcn");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd solution/web && npm test -- Setup`
Expected: FAIL — no Detect button on the handbrake step.

- [ ] **Step 3: Write the implementation**

In `solution/web/src/pages/Setup.tsx`, add the import:

```tsx
import { detectEncoders } from "../api/client";
```

add state:

```tsx
  const [encFamily, setEncFamily] = useState("auto");
  const [encFound, setEncFound] = useState<string | null>(null);
  const [encError, setEncError] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);
```

add the handler:

```tsx
  async function detect() {
    setDetecting(true);
    setEncError(null);
    setEncFound(null);
    try {
      const res = await detectEncoders(handbrake);
      if (!res.ok) {
        setEncError(res.error ?? "Detection failed");
        return;
      }
      // Hardware before software, matching the backend's auto priority.
      const best = res.families.find(f => f.available && f.hardware);
      setEncFamily(best ? best.id : "cpu");
      setEncFound(best
        ? `Found ${best.label} — using hardware H.265 encoding.`
        : "No hardware encoder found — using CPU x265.");
    } catch {
      setEncError("Detection failed");
    } finally {
      setDetecting(false);
    }
  }
```

change `saveHandbrake` to persist the family too:

```tsx
  async function saveHandbrake() {
    setBusy(true);
    try {
      await updateSettings({ handbrake_cli: handbrake, encoder_family: encFamily });
    } finally {
      setBusy(false);
      setStep("done");
    }
  }
```

and extend the handbrake step's JSX, after the `<Input .../>`:

```tsx
              <div className="flex items-center gap-2">
                <Button variant="outline" onClick={detect} disabled={detecting}
                  aria-busy={detecting}>
                  {detecting ? "Detecting…" : "Detect"}
                </Button>
                {encFound && <span className="text-xs text-muted">{encFound}</span>}
                {encError && <span className="text-xs text-state-failed">{encError}</span>}
              </div>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd solution/web && npm test -- Setup`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solution/web/src/pages/Setup.tsx solution/web/src/pages/Setup.test.tsx
git commit -m "feat(web): detect encoders during first-run setup"
```

---

### Task 11: Documentation and full-suite verification

**Files:**
- Modify: `CLAUDE.md` (endpoint list, Settings screen description, architecture module list)
- Modify: `solution/.env.example` (document `ENCODER_FAMILY`)

**Interfaces:**
- Consumes: everything above. Produces: no code.

- [ ] **Step 1: Run the entire backend suite**

Run: `python -m pytest`
Expected: PASS, no regressions. Fix anything red before continuing — in particular any
pre-existing test that asserted the hardcoded NVENC preset.

- [ ] **Step 2: Run the entire frontend suite**

Run: `cd solution/web && npm test`
Expected: PASS, including the `tsc -b` typecheck that runs first.

- [ ] **Step 3: Update the docs**

In `CLAUDE.md`, add to the key-endpoints paragraph:

```
`GET /api/encoders` (family catalog + cached availability), `POST /api/encoders/detect`
(probes HandBrakeCLI and caches what it finds),
```

In the Screens sentence, change the Settings description to note the encoder family
selector:

```
Settings (connections, scheduler, encoder — an encoder-family selector with hardware
detection (AMD VCN / NVIDIA NVENC / Intel QSV / CPU x265 / Custom) plus an optional
CPU fallback, security, ...)
```

In the Key modules list, add after `engine/worker.py`:

```
- `encoders.py` — encoder family catalog, HandBrake capability probe (parses the
  `--version` banner), and per-job preset resolution with optional CPU fallback
```

In the External Dependencies section, replace the NVENC-only preset line with:

```
  - Presets are chosen by encoder family: AMD `H.265 VCN 1080p` / `H.265 VCN 2160p 4K`,
    NVIDIA `H.265 NVENC 1080p` / `H.265 NVENC 2160p 4K`, Intel `H.265 QSV 1080p` /
    `H.265 QSV 2160p 4K`, CPU `H.265 MKV 1080p30` / `H.265 MKV 2160p60 4K`
```

Append to `solution/.env.example`:

```
# Encoder family: auto | vcn | nvenc | qsv | cpu | custom (default auto — detects
# your hardware). PRESET_1080/PRESET_4K are only used when set to 'custom'.
ENCODER_FAMILY=auto
```

- [ ] **Step 4: Verify the docs build nothing and the suites are still green**

Run: `python -m pytest -q` and `cd solution/web && npm test`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md solution/.env.example
git commit -m "docs: document encoder family selection and detection endpoints"
```

---

## Manual verification on this machine

After Task 11, confirm the feature end-to-end against real hardware (AMD Ryzen 9800X3D +
RX 9070 XT, HandBrakeCLI at `C:\HandBrake\HandBrakeCLI.exe`):

1. Build the UI and start the server:
   `cd solution/web && npm run build`, then `cd solution && python -m transcoder.api`
2. Open `http://localhost:8765`, log in, go to **Settings → Encoder**.
3. Set the HandBrake CLI path to `C:\HandBrake\HandBrakeCLI.exe` and click **Detect**.
   Expect: `AMD VCN: available`, `CPU (x265): available`, `NVIDIA NVENC: not available`,
   `Intel QSV: not available`.
4. Leave the encoder on **Auto**, save, and confirm a queued job's log shows
   `preset H.265 VCN 1080p`.
5. Select **NVIDIA NVENC**, save, and confirm the inline warning appears and a job logs
   the CPU fallback line.
