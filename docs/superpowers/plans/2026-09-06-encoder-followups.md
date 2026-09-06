# Encoder Follow-Ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all 33 review findings deferred during the AMD encoder-support branch, without weakening the invariants that branch was built on.

**Architecture:** No new modules and no behaviour change for a user on a supported path. The work is four kinds of change: (a) hardening two spots where malformed input reads as *confident* data, (b) closing the API-boundary half of a validation defect whose `.env` half is already fixed, (c) filling test-coverage holes that leave real branches unguarded, (d) tidying dead code, types and docs.

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy / pytest; React 18 + TypeScript / Vite / Vitest.

**Spec:** `docs/superpowers/specs/2026-09-05-amd-encoder-support-design.md` (the design this follows up on). The deferred-finding list itself is reproduced per-task below — it was recovered from the session transcript after the SDD ledger was deleted.

## Global Constraints

- **"Unknown is not unavailable."** A failed, missing or unrecognised probe must never read as "encoder absent". No task may make an absence imply unavailability.
- **Empty-set-means-unknown.** A *successful* parse always contains `cpu`, so an empty `available` set is unambiguously "probe failed / never ran". Keep that total.
- **Unknown must never harden into the DB.** `detect_and_store` refuses to cache an empty result. Task 4 adds a process-local memo; it must not change this.
- **Preset-catalog order is load-bearing.** `_payload` iterates `FAMILIES.items()`; the frontend Setup wizard depends on that order. Never reorder `FAMILIES`.
- **`repo.py` helpers never commit.** Callers own the transaction boundary.
- **TDD is mandatory** (CLAUDE.md): write the failing test, watch it fail, then implement.
- **Backend tests:** `python -m pytest` from the **repo root** (`pytest.ini` sets `pythonpath = solution`). Never `cd solution` to run pytest.
- **Frontend tests:** `npm test` from `solution/web` — runs `tsc -b` before Vitest, so type errors fail the suite.
- **Baselines at plan time:** backend 270 passed / 1 skipped / 1 warning; frontend 19 files / 76 tests. Counts may only go up.
- **Never bypass hooks or signing** (`--no-verify`, `--no-gpg-sign`).
- **Windows:** avoid PowerShell here-strings for commit messages; use plain `-m` or `git commit -F <file>`.
- **Workers do not commit.** Leave changes in the working tree; the controller commits per task. Concurrent agents race on `.git/index.lock`.
- **`EncoderFamily` is already an interface name** in `solution/web/src/api/types.ts`. The new union type must be called `EncoderFamilyId`.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `solution/transcoder/encoders.py` | Family catalog, banner parsing, capability cache, preset resolution | 1, 2, 3, 4 |
| `solution/transcoder/api/schemas.py` | Request/response shapes | 6, 7 |
| `solution/transcoder/api/routers/settings.py` | Settings write path | 6, 8, 9 |
| `solution/transcoder/api/routers/encoders.py` | Encoder catalog + detect endpoints | 7, 8 |
| `tests/conftest.py`, `tests/api_conftest.py` | Shared fixtures | 11 |
| `solution/web/src/api/types.ts` | Shared TS types | 12 |
| `solution/web/src/pages/Setup.tsx` | First-run wizard | 12, 14 |
| `CLAUDE.md`, `.env.example` | Docs | 16 |

---

## Execution Waves

Tasks within a wave touch disjoint files and run in parallel. Waves are sequential.

| Wave | Tasks | Why grouped |
|---|---|---|
| A | 1, 10, 11, 13, 16 | Disjoint; no dependencies |
| B | 2, 7, 12 | `encoders.py` / encoders router / frontend types |
| C | 3, 6, 14 | `encoders.py` / settings write path / Setup page |
| D | 4, 8, 15 | `encoders.py` / routers / Setup tests |
| E | 5, 9 | Tests-only; Task 9 needs Task 4's `reset_probe_cache` |

**Delegation:** Tasks 1, 5, 8, 10, 11, 13, 15, 16 are mechanical and narrow — dispatch to the OpusForge `local_worker`. Tasks 2, 3, 4, 6, 7, 9, 12, 14 involve design judgement — hosted agent. Every task is reviewed on Opus regardless of who implemented it.

---

### Task 1: encoders.py dead code and placement

Closes: *log at bottom of module*; *dead `nvEncodeAPI` alternative*; *undocumented lazy-import rationale*.

**Files:**
- Modify: `solution/transcoder/encoders.py`
- Test: `tests/test_encoders.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no signature changes. Every existing public name stays.

- [ ] **Step 1: Write the failing test**

`nvEncodeAPI` is a redundant alternative in `_BANNER_MENTIONS_RE`: the literal banner text `Cannot load nvEncodeAPI64.dll` already contains the substring `nvEnc`, which the `nvenc` alternative matches under `re.IGNORECASE`. Removing it must not change behaviour — pin that first.

```python
def test_nvenc_dll_line_alone_is_a_recognised_banner():
    """The real-world NVIDIA-missing banner has no '<family>:' line at all.
    It must still count as 'we understood this banner', otherwise a working
    AMD box with no NVIDIA runtime would report unknown."""
    banner = "[11:44:47] Cannot load nvEncodeAPI64.dll\nHandBrake 1.11.2\n"
    assert encoders.parse_capabilities(banner) == {"cpu"}
    assert encoders.parse_unavailable(banner) == {"nvenc"}
```

- [ ] **Step 2: Run it and confirm it passes BEFORE the change**

Run: `python -m pytest tests/test_encoders.py -k nvenc_dll_line_alone -v`
Expected: PASS. This is a characterisation test — it locks in today's behaviour so Step 3 cannot regress it.

- [ ] **Step 3: Make the three changes**

1. Move `log = logging.getLogger("transcoder")` from line ~210 up to just below the imports (before `AUTO = "auto"`).
2. In `_BANNER_MENTIONS_RE`, drop the `|nvEncodeAPI` alternative:

```python
# "nvEncodeAPI64.dll" already contains "nvEnc", which the nvenc alternative
# matches case-insensitively, so it needs no alternative of its own.
_BANNER_MENTIONS_RE = re.compile(r"(vcn|nvenc|qsv)", re.IGNORECASE)
```

3. Add this comment above the first in-function import, and hoist the `transcoder.config` one to module scope (it has no import-time side effect; `transcoder.db` builds an engine at import time, which is why the *repo* imports must stay lazy):

```python
# transcoder.repo pulls in transcoder.db, which constructs a SQLAlchemy engine
# at import time. Importing it at module scope would make merely importing this
# catalog open a database connection, so the repo imports stay function-local.
# transcoder.config has no such side effect and is imported normally above.
```

- [ ] **Step 4: Run the suite**

Run: `python -m pytest -q`
Expected: 270 passed + your 1 new test, 1 skipped.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 2: Harden `load_capabilities` against malformed blobs

Closes: *`set(blob["available"])` with no type check*; *non-None `detected_at` beside an empty set contradicts the docstring*.

**Files:**
- Modify: `solution/transcoder/encoders.py`
- Test: `tests/test_encoders_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `load_capabilities(session) -> tuple[set[str], set[str], str | None]` — unchanged signature, stricter guarantees: when the returned `available` set is empty, `detected_at` is now always `None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_load_capabilities_rejects_a_non_list_available(session):
    """A bare string parses to a set of CHARACTERS -- {"v","c","n"} -- which is
    truthy and therefore reads as 'capabilities known'. That silently disables
    the unknown-is-not-unavailable guard, so it must be rejected as corrupt."""
    set_setting(session, CAPABILITIES_KEY, json.dumps(
        {"available": "vcn", "detected_at": "2026-01-01T00:00:00+00:00"}))
    session.commit()
    assert load_capabilities(session) == (set(), set(), None)


def test_load_capabilities_rejects_non_string_members(session):
    set_setting(session, CAPABILITIES_KEY, json.dumps(
        {"available": ["vcn", 7], "detected_at": "2026-01-01T00:00:00+00:00"}))
    session.commit()
    assert load_capabilities(session) == (set(), set(), None)


def test_load_capabilities_ignores_a_non_list_unavailable(session):
    """A corrupt NEGATIVE list must degrade to 'no explicit negatives' rather
    than poisoning the whole read: negatives are the only thing that may
    substitute an encoder away from the user's choice."""
    set_setting(session, CAPABILITIES_KEY, json.dumps(
        {"available": ["vcn", "cpu"], "unavailable": "qsv",
         "detected_at": "2026-01-01T00:00:00+00:00"}))
    session.commit()
    available, unavailable, detected_at = load_capabilities(session)
    assert available == {"vcn", "cpu"}
    assert unavailable == set()
    assert detected_at == "2026-01-01T00:00:00+00:00"


def test_load_capabilities_nulls_detected_at_when_available_is_empty(session):
    """empty-set-means-unknown must be total: a timestamp beside an empty set
    would let a caller conclude 'we successfully detected nothing'."""
    set_setting(session, CAPABILITIES_KEY, json.dumps(
        {"available": [], "detected_at": "2026-01-01T00:00:00+00:00"}))
    session.commit()
    assert load_capabilities(session) == (set(), set(), None)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_encoders_db.py -k load_capabilities -v`
Expected: the four new tests FAIL.

- [ ] **Step 3: Implement**

Replace the body of `load_capabilities` after the `raw` guard:

```python
    def _str_set(value) -> set[str] | None:
        """None means 'malformed'. A bare string is the dangerous case: it would
        iterate into a truthy set of single characters."""
        if value is None:
            return set()
        if not isinstance(value, (list, tuple)):
            return None
        if not all(isinstance(v, str) for v in value):
            return None
        return set(value)

    try:
        blob = json.loads(raw)
        available = _str_set(blob["available"])
        unavailable = _str_set(blob.get("unavailable"))
        if available is None:
            raise ValueError("available is not a list of strings")
        if unavailable is None:
            # A corrupt negative list degrades to "no explicit negatives" --
            # the safe direction -- rather than discarding a valid positive set.
            log.warning("Ignoring corrupt 'unavailable' in %s", CAPABILITIES_KEY)
            unavailable = set()
        detected_at = blob.get("detected_at")
        if not available:
            # empty-set-means-unknown is total: no timestamp without a result.
            return set(), set(), None
        return available, unavailable, detected_at
    except (ValueError, KeyError, TypeError):
        log.warning("Ignoring corrupt %s setting", CAPABILITIES_KEY)
        return set(), set(), None
```

Update the docstring to state the new guarantee.

- [ ] **Step 4: Run tests**

Run: `python -m pytest -q`
Expected: green, count up by 4.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 3: Blank custom presets must not reach HandBrake

Closes: *custom family with empty preset strings returns `Resolution("","")` unvalidated*.

**Files:**
- Modify: `solution/transcoder/encoders.py`
- Test: `tests/test_encoders.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `resolve()` signature unchanged. New behaviour: `family="custom"` with a blank `custom_1080` or `custom_4k` yields the CPU preset pair with `substituted=True`.

- [ ] **Step 1: Write the failing tests**

```python
def test_custom_with_blank_presets_falls_back_to_cpu():
    """Handing HandBrake --preset "" fails the job with an opaque error. CPU
    x265 is slow but correct, and substituted=True makes the swap visible in
    the job log."""
    r = encoders.resolve("custom", {"vcn", "cpu"}, custom_1080="", custom_4k="")
    assert (r.preset_1080, r.preset_4k) == ("H.265 MKV 1080p30", "H.265 MKV 2160p60 4K")
    assert r.family == "cpu"
    assert r.requested == "custom"
    assert r.substituted is True


def test_custom_with_one_blank_preset_falls_back_to_cpu():
    r = encoders.resolve("custom", {"cpu"}, custom_1080="Fast 1080p30", custom_4k="   ")
    assert r.family == "cpu"
    assert r.substituted is True


def test_custom_with_both_presets_set_is_untouched():
    r = encoders.resolve("custom", {"cpu"}, custom_1080="Fast 1080p30", custom_4k="Fast 2160p60")
    assert (r.preset_1080, r.preset_4k) == ("Fast 1080p30", "Fast 2160p60")
    assert r.family == "custom"
    assert r.substituted is False
```

Also add the equivalent for the `family not in FAMILIES` defensive branch, which routes through the same custom path:

```python
def test_unrecognised_family_with_blank_presets_falls_back_to_cpu():
    r = encoders.resolve("wat", {"cpu"}, custom_1080="", custom_4k="")
    assert r.family == "cpu"
    assert r.requested == "wat"
    assert r.substituted is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_encoders.py -k custom -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add a helper above `resolve` and use it in both custom branches:

```python
def _custom_or_cpu(custom_1080: str, custom_4k: str, requested: str,
                   unknown: bool) -> Resolution:
    """Custom presets, unless either is blank -- an empty --preset argument
    fails the job with an opaque HandBrake error, so fall back to CPU and mark
    the swap so the worker logs it."""
    if not (custom_1080 or "").strip() or not (custom_4k or "").strip():
        log.warning(
            "Custom encoder selected but presets are blank; using CPU x265 presets"
        )
        p1080, p4k = _presets(CPU)
        return Resolution(p1080, p4k, CPU, requested, True, unknown)
    return Resolution(custom_1080, custom_4k, CUSTOM, requested, False, unknown)
```

Then:

```python
    if family == CUSTOM:
        return _custom_or_cpu(custom_1080, custom_4k, CUSTOM, unknown)
    ...
    if family not in FAMILIES:
        # Defensive: an unrecognised stored value behaves like custom.
        return _custom_or_cpu(custom_1080, custom_4k, family, unknown)
```

**Check the consumer:** `solution/transcoder/engine/worker.py` reads `resolution.substituted` and logs `FAMILIES[resolution.requested]["label"]`. `requested` can now be `"custom"` or an unrecognised string, neither of which is a `FAMILIES` key. Verify the worker's log branch cannot `KeyError`; if it can, guard it with `FAMILIES.get(resolution.requested, {}).get("label", resolution.requested)`. **You may edit `worker.py` for this guard only.**

- [ ] **Step 4: Run tests**

Run: `python -m pytest -q`
Expected: green, count up by 4.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 4: Process-local memo for an unknown probe result

Closes: *a HandBrake build whose banner mentions no hardware family re-probes on EVERY job*.

**Files:**
- Modify: `solution/transcoder/encoders.py`
- Test: `tests/test_encoders_probe.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `reset_probe_cache() -> None` at module scope. **Task 9 calls this** when the user edits the HandBrake CLI path.

**Design note — read before coding.** The DB deliberately never caches an unknown result, so `auto` re-probes until HandBrake works. That is correct and must not change. The cost is one subprocess *per job* for a host whose banner we cannot read. Fix it with an in-memory memo that dies with the process: restart-to-retry stays true, and nothing unknown is ever written to the DB.

- [ ] **Step 1: Write the failing tests**

```python
def test_unknown_probe_is_memoised_within_a_process(session, monkeypatch):
    calls = []

    def fake_probe(cli, timeout=30.0):
        calls.append(cli)
        return set(), set()          # unrecognised banner -> unknown

    monkeypatch.setattr(encoders, "probe", fake_probe)
    encoders.reset_probe_cache()

    for _ in range(3):
        assert encoders.get_or_detect_capabilities(session, "hb.exe") == (set(), set(), None)
    assert len(calls) == 1, "unknown result should be probed once per process"


def test_reset_probe_cache_forces_a_reprobe(session, monkeypatch):
    calls = []
    monkeypatch.setattr(encoders, "probe",
                        lambda cli, timeout=30.0: (calls.append(cli), (set(), set()))[1])
    encoders.reset_probe_cache()
    encoders.get_or_detect_capabilities(session, "hb.exe")
    encoders.reset_probe_cache()
    encoders.get_or_detect_capabilities(session, "hb.exe")
    assert len(calls) == 2


def test_memo_is_keyed_on_the_cli_path(session, monkeypatch):
    """A different binary is a different question -- changing the path must not
    inherit the old binary's 'unknown'."""
    calls = []
    monkeypatch.setattr(encoders, "probe",
                        lambda cli, timeout=30.0: (calls.append(cli), (set(), set()))[1])
    encoders.reset_probe_cache()
    encoders.get_or_detect_capabilities(session, "old.exe")
    encoders.get_or_detect_capabilities(session, "new.exe")
    assert calls == ["old.exe", "new.exe"]


def test_a_successful_probe_is_not_memoised_as_unknown(session, monkeypatch):
    """A good result goes to the DB; the memo must not shadow it."""
    monkeypatch.setattr(encoders, "probe",
                        lambda cli, timeout=30.0: ({"vcn", "cpu"}, {"qsv"}))
    encoders.reset_probe_cache()
    available, unavailable, detected_at = encoders.get_or_detect_capabilities(session, "hb.exe")
    assert available == {"vcn", "cpu"}
    assert detected_at is not None
```

Add an autouse fixture in this file so the memo cannot leak between tests:

```python
@pytest.fixture(autouse=True)
def _clear_probe_memo():
    encoders.reset_probe_cache()
    yield
    encoders.reset_probe_cache()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_encoders_probe.py -v`
Expected: FAIL with `AttributeError: module 'transcoder.encoders' has no attribute 'reset_probe_cache'`.

- [ ] **Step 3: Implement**

```python
# Process-local memo of CLI paths whose probe came back unknown. The DB must
# never cache "unknown" (a broken HandBrake that gets fixed has to be picked up
# without a manual reset), but without this a permanently unreadable banner
# costs one subprocess per job. Dying with the process keeps restart-to-retry.
_unknown_probes: set[str] = set()


def reset_probe_cache() -> None:
    """Forget memoised unknown probes. Call when the HandBrake path changes."""
    _unknown_probes.clear()
```

Then in `get_or_detect_capabilities`, after the DB read returns nothing:

```python
    available, unavailable, detected_at = load_capabilities(session)
    if available:
        return available, unavailable, detected_at
    if handbrake_cli in _unknown_probes:
        return set(), set(), None
    result = detect_and_store(session, handbrake_cli)
    if not result[0]:
        _unknown_probes.add(handbrake_cli)
    return result
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest -q`
Expected: green, count up by 4.

- [ ] **Step 5: Report to the controller (do not commit).** Tell the controller explicitly that `reset_probe_cache` now exists, so Task 9 can be released.

---

### Task 5: Fill the encoder test-coverage holes

Closes: *no uppercase-banner test despite `re.IGNORECASE`*; *`or ""` 4k fallback in `migrate_encoder_family` untested*; *no `probe → store → commit → reuse` test*; *duplicate/subsumed tests in `test_encoders.py`*.

**Files:**
- Test: `tests/test_encoders.py`, `tests/test_encoders_db.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4 must already be in the tree.
- Produces: nothing.

- [ ] **Step 1: Add the three missing tests**

```python
def test_banner_parsing_is_case_insensitive():
    """Both banner regexes set re.IGNORECASE but nothing pinned it, so a
    refactor could drop the flag silently."""
    banner = "[11:44:47] VCN: IS AVAILABLE\n[11:44:47] QSV: NOT AVAILABLE ON THIS SYSTEM\n"
    assert encoders.parse_capabilities(banner) == {"vcn", "cpu"}
    assert encoders.parse_unavailable(banner) == {"qsv"}
```

```python
def test_migrate_uses_empty_string_when_only_the_1080_preset_exists(session):
    """The `or ""` fallback on handbrake_preset_4k had no coverage. A half-set
    preset pair is a hand-tuned install -> custom."""
    set_setting(session, "handbrake_preset_1080", "H.265 NVENC 1080p")
    session.commit()
    assert migrate_encoder_family(session) == CUSTOM
```

```python
def test_probe_result_survives_commit_and_is_reused(session, monkeypatch):
    """resolve_for_job writes the cache without committing (callers own the
    transaction). If a call site stopped committing, every job would re-probe
    with a 30s timeout and no test would notice."""
    calls = []
    monkeypatch.setattr(encoders, "probe",
                        lambda cli, timeout=30.0: (calls.append(cli), ({"vcn", "cpu"}, {"qsv"}))[1])
    encoders.reset_probe_cache()

    available, _u, detected_at = encoders.get_or_detect_capabilities(session, "hb.exe")
    assert available == {"vcn", "cpu"} and detected_at is not None
    session.commit()

    again = encoders.get_or_detect_capabilities(session, "hb.exe")
    assert again[0] == {"vcn", "cpu"}
    assert len(calls) == 1, "second read must come from the committed cache"
```

- [ ] **Step 2: Run them**

Run: `python -m pytest tests/test_encoders.py tests/test_encoders_db.py -q`
Expected: PASS (these characterise existing behaviour).

- [ ] **Step 3: De-duplicate `tests/test_encoders.py`**

Read the whole file. Find tests where one is a strict subset of another (same function under test, same inputs, weaker assertions). Delete the weaker one, keeping the stronger. **Do not reduce real coverage** — if two tests differ in any input or assertion, keep both. List every deletion in your report with a one-line justification.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: green. Net count = 270 + additions from Tasks 1–4 + 3 − (deletions).

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 6: Validate `encoder_family` at the API boundary

Closes: *`PUT /api/settings` accepts any `encoder_family` string* — the unfixed half of finding A1 (the `.env` half landed in commit `3b9a5c6`).

**Files:**
- Modify: `solution/transcoder/api/schemas.py`, `solution/transcoder/api/routers/settings.py`
- Test: `tests/test_api_settings_encoder.py` (create)

**Interfaces:**
- Consumes: `encoders.FAMILIES`, `encoders.AUTO`, `encoders.CUSTOM`.
- Produces: `PUT /api/settings` returns 422 for an unrecognised family.

**Why this matters:** the settings router writes `encoder_family` through the untyped `simple_fields` loop. An invalid value is sticky, and `resolve()` routes it through the custom branch onto whatever presets are stored — which on a fresh install are the hardcoded NVENC defaults. On AMD that fails every job.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

VALID = ["auto", "vcn", "nvenc", "qsv", "cpu", "custom"]


@pytest.mark.parametrize("family", VALID)
def test_valid_encoder_family_is_accepted(api, family):
    client, _ = api
    r = client.put("/api/settings", json={"encoder_family": family})
    assert r.status_code == 200


@pytest.mark.parametrize("family", ["amd", "vce", "nvidia", "x265", "VCN ", "wat"])
def test_invalid_encoder_family_is_rejected(api, family):
    """A typo must fail loudly at the boundary rather than persisting into a
    sticky row that silently degrades to the custom-preset path."""
    client, _ = api
    r = client.put("/api/settings", json={"encoder_family": family})
    assert r.status_code == 422


def test_rejected_family_is_not_persisted(api):
    client, Session = api
    client.put("/api/settings", json={"encoder_family": "amd"})
    with Session() as s:
        from transcoder.repo import get_setting
        assert get_setting(s, "encoder_family") != "amd"
```

Use the shared `api` fixture from `tests/api_conftest.py`; match how the existing settings tests obtain it.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_api_settings_encoder.py -v`
Expected: the invalid-family tests FAIL with 200.

- [ ] **Step 3: Implement**

In `schemas.py`, on the settings-update model, type the field as a literal built from the catalog rather than a hand-typed list:

```python
from typing import Literal
from transcoder.encoders import AUTO, CUSTOM, FAMILIES

# Built from the catalog so a new family cannot be added to encoders.py and
# silently rejected here.
EncoderFamilyId = Literal[tuple([AUTO, *FAMILIES.keys(), CUSTOM])]  # type: ignore[valid-type]
```

If a dynamically-built `Literal` proves awkward for pydantic in this codebase, write the six values out explicitly **and** add a test asserting the schema's allowed set equals `{AUTO, *FAMILIES, CUSTOM}`, so the two cannot drift:

```python
def test_schema_family_literal_matches_the_catalog():
    from transcoder.encoders import AUTO, CUSTOM, FAMILIES
    from transcoder.api import schemas
    allowed = set(get_args(schemas.SettingsUpdate.model_fields["encoder_family"].annotation))
    assert allowed - {None} == {AUTO, *FAMILIES, CUSTOM}
```

Change the field to `encoder_family: EncoderFamilyId | None = None`. The existing `simple_fields` loop then needs no change — pydantic rejects the bad value before the router runs.

- [ ] **Step 4: Run tests**

Run: `python -m pytest -q`
Expected: green. Confirm no existing test sent a bogus family and now 422s; if one does, fix the test, not the validation.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 7: Response models for the encoder routes

Closes: *no `response_model` on either route*.

**Files:**
- Modify: `solution/transcoder/api/routers/encoders.py`
- Test: `tests/test_api_encoders.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `EncoderFamilyOut`, `EncodersOut`, `DetectOut` in the encoders router module.

**Constraint:** the frontend depends on `families` arriving in `FAMILIES` insertion order (`vcn, nvenc, qsv, cpu`). A response model must not reorder or drop keys.

- [ ] **Step 1: Write the failing test**

```python
def test_encoders_response_shape_and_order(api):
    client, _ = api
    r = client.get("/api/encoders")
    assert r.status_code == 200
    body = r.json()
    assert [f["id"] for f in body["families"]] == ["vcn", "nvenc", "qsv", "cpu"]
    assert set(body) == {"available", "detected_at", "families"}
    for f in body["families"]:
        assert set(f) == {"id", "label", "preset_1080", "preset_4k", "hardware", "available"}


def test_encoders_routes_declare_response_models():
    """The shape is a hard contract for committed frontend code; without a
    response_model it is absent from OpenAPI and unchecked by pydantic."""
    from transcoder.api.routers import encoders as r
    from transcoder.api.app import create_app
    schema = create_app(start_worker=False).openapi()
    get_op = schema["paths"]["/api/encoders"]["get"]
    assert "application/json" in get_op["responses"]["200"]["content"]
    assert "$ref" in str(get_op["responses"]["200"]["content"]["application/json"]["schema"])
```

Match how other tests in this file build the app; if `create_app` takes different arguments, use the established pattern.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_api_encoders.py -v`

- [ ] **Step 3: Implement**

```python
class EncoderFamilyOut(BaseModel):
    id: str
    label: str
    preset_1080: str
    preset_4k: str
    hardware: bool
    available: bool


class EncodersOut(BaseModel):
    available: list[str]
    detected_at: str | None = None
    families: list[EncoderFamilyOut]


class DetectOut(EncodersOut):
    ok: bool
    error: str | None = None
```

Annotate `@router.get("", response_model=EncodersOut)` and `@router.post("/detect", response_model=DetectOut)`. `_payload` already emits `families` as a list comprehension over `FAMILIES.items()`, so order is preserved — do not change it.

- [ ] **Step 4: Run tests**

Run: `python -m pytest -q`
Expected: green.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 8: Shared setting-key constants and a whitespace-safe CLI path

Closes: *router uses bare `"encoder_family"` literals instead of `FAMILY_KEY`/`FALLBACK_KEY`*; *whitespace-only CLI path is truthy, yielding `Could not run .`*.

**Files:**
- Modify: `solution/transcoder/api/routers/settings.py`, `solution/transcoder/api/routers/encoders.py`
- Test: `tests/test_api_encoders.py`

**Interfaces:**
- Consumes: `encoders.FAMILY_KEY`, `encoders.FALLBACK_KEY`.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```python
def test_whitespace_only_cli_path_reports_not_set(api):
    """A whitespace path is truthy, so it used to be probed -- the user saw
    'Could not run .' instead of the friendly not-set message."""
    client, _ = api
    r = client.post("/api/encoders/detect", json={"handbrake_cli": "   "})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "HandBrake CLI path is not set"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_api_encoders.py -k whitespace -v`
Expected: FAIL — error text is `Could not run    .`

- [ ] **Step 3: Implement**

In `routers/encoders.py`:

```python
    cli = (body.handbrake_cli or get_effective(db, "handbrake_cli", _cfg.settings.HANDBRAKE_CLI) or "").strip()
    if not cli:
        return {"ok": False, "error": "HandBrake CLI path is not set", **_payload(set(), None)}
```

In `routers/settings.py`, replace the two bare literals in `simple_fields` with the constants and add the comment:

```python
from transcoder.encoders import FAMILY_KEY, FALLBACK_KEY

    simple_fields = [
        "sonarr_url", "radarr_url", "sftp_host", "sftp_port", "sftp_username",
        "handbrake_cli", "handbrake_preset_1080", "handbrake_preset_4k",
        # These two keys are also read by transcoder.encoders, so they use the
        # shared constants; the rest are local to this router and stay literal.
        FAMILY_KEY, FALLBACK_KEY,
        "scheduler_run_at_startup", "webhook_username",
    ]
```

`getattr(body, field, None)` still works because the constants' *values* are the field names.

- [ ] **Step 4: Run tests**

Run: `python -m pytest -q`
Expected: green, count up by 1.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 9: Invalidate the capability cache when the HandBrake path changes

Closes: *detection result not invalidated when the CLI path is edited afterwards — can persist a family probed against a different binary*.

**Files:**
- Modify: `solution/transcoder/api/routers/settings.py`
- Test: `tests/test_api_settings_encoder.py`

**Interfaces:**
- Consumes: `encoders.reset_probe_cache()` (Task 4), `encoders.CAPABILITIES_KEY`.
- Produces: nothing.

**Blocked on Task 4.** Do not start until the controller confirms `reset_probe_cache` is in the tree.

- [ ] **Step 1: Write the failing tests**

```python
def test_changing_the_handbrake_path_clears_the_capability_cache(api):
    """A family probed against a different binary must not persist. This is the
    same hazard the post-restore clear fixes, reached by a different route."""
    client, Session = api
    from transcoder.repo import get_setting, set_setting
    from transcoder.encoders import CAPABILITIES_KEY

    with Session() as s:
        set_setting(s, "handbrake_cli", "C:/old/HandBrakeCLI.exe")
        set_setting(s, CAPABILITIES_KEY, '{"available":["nvenc","cpu"],"detected_at":"x"}')
        s.commit()

    client.put("/api/settings", json={"handbrake_cli": "C:/new/HandBrakeCLI.exe"})

    with Session() as s:
        assert not get_setting(s, CAPABILITIES_KEY)


def test_resaving_the_same_handbrake_path_keeps_the_cache(api):
    """Only an actual change invalidates -- saving the settings form unchanged
    must not force a re-probe."""
    client, Session = api
    from transcoder.repo import get_setting, set_setting
    from transcoder.encoders import CAPABILITIES_KEY
    blob = '{"available":["vcn","cpu"],"detected_at":"x"}'

    with Session() as s:
        set_setting(s, "handbrake_cli", "C:/hb/HandBrakeCLI.exe")
        set_setting(s, CAPABILITIES_KEY, blob)
        s.commit()

    client.put("/api/settings", json={"handbrake_cli": "C:/hb/HandBrakeCLI.exe"})

    with Session() as s:
        assert get_setting(s, CAPABILITIES_KEY) == blob


def test_changing_the_path_also_resets_the_process_memo(api, monkeypatch):
    from transcoder import encoders
    called = []
    monkeypatch.setattr(encoders, "reset_probe_cache", lambda: called.append(True))
    client, _ = api
    client.put("/api/settings", json={"handbrake_cli": "C:/another/HandBrakeCLI.exe"})
    assert called
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_api_settings_encoder.py -k handbrake -v`

- [ ] **Step 3: Implement**

Capture the old value *before* the `simple_fields` loop writes the new one, and act after it:

```python
    from transcoder import encoders as _enc

    previous_cli = get_setting(db, "handbrake_cli")

    # ... existing simple_fields loop ...

    new_cli = getattr(body, "handbrake_cli", None)
    if new_cli is not None and new_cli not in ("", _REDACTED) and new_cli != previous_cli:
        # The cached families were probed against the OLD binary. Blank the blob
        # (falsy raw == unknown) rather than deleting the row, mirroring the
        # post-restore clear, and drop the process-local memo too.
        set_setting(db, _enc.CAPABILITIES_KEY, "")
        _enc.reset_probe_cache()
        updated.append("encoder_capabilities_cleared")
```

Place it before the existing `db.commit()`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest -q`
Expected: green, count up by 3.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 10: Pin the conditional commit in the app lifespan

Closes: *the conditional commit at `app.py:54-55` is unpinned — deleting it leaves both tests green*.

**Files:**
- Test: `tests/test_app_migration_commit.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. **This task adds no production code.**

**Why it is currently invisible:** `migrate_encoder_family` writes `encoder_family` and the lifespan commits it, but `seed_settings_from_env` commits unconditionally immediately afterwards — so deleting the `if migrate_encoder_family(_db) is not None: _db.commit()` commit changes nothing observable in the existing tests. Pin it by asserting the commit happens *before* the seeder runs.

- [ ] **Step 1: Write the test**

Spy on the session and record the order of `commit()` calls relative to `seed_settings_from_env`:

```python
def test_encoder_family_is_committed_before_the_seeder_runs(monkeypatch):
    """If the migration's own commit is removed, the family row rides on the
    seeder's commit -- fine today, silently broken the moment the seeder is
    reordered or made conditional."""
    order = []

    import transcoder.api.app as app_module
    real_seed = app_module.seed_settings_from_env

    def spy_seed(db, mapping):
        order.append("seed")
        return real_seed(db, mapping)

    monkeypatch.setattr(app_module, "seed_settings_from_env", spy_seed)

    import transcoder.encoders as enc
    real_migrate = enc.migrate_encoder_family

    def spy_migrate(session):
        value = real_migrate(session)
        original_commit = session.commit

        def tracking_commit():
            order.append("commit-after-migrate")
            session.commit = original_commit
            return original_commit()

        session.commit = tracking_commit
        return value

    monkeypatch.setattr(enc, "migrate_encoder_family", spy_migrate)

    # boot the app with the real lifespan (see tests/test_api_health.py for the
    # `with TestClient(app) as client:` pattern) ...

    assert order == ["commit-after-migrate", "seed"]
```

Complete the boot section using the same in-memory-engine setup the `booted_api` fixture uses (Task 11 extracts it into a shared helper — if that has already landed, reuse it; otherwise inline it and note that for the controller).

- [ ] **Step 2: Run it and confirm it passes**

Run: `python -m pytest tests/test_app_migration_commit.py -v`

- [ ] **Step 3: Prove the test actually pins the behaviour**

Temporarily delete the two lines `if migrate_encoder_family(_db) is not None:` / `_db.commit()` in `app.py` (replace with a bare call). Re-run — the test **must fail**. Then restore `app.py` exactly. Report both outcomes; a test that passes either way is worthless.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: green, count up by 1, and `git diff solution/` shows no change.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 11: Test-fixture hygiene

Closes: *`booted_api` duplicates ~12 monkeypatch lines*; *first migration test subsumed by the second*; *test asserts a literal that flows from a config default*; *the `"auto"` default test cannot discriminate*; *conftest `try/except ImportError` is dead and fails open*.

**Files:**
- Modify: `tests/conftest.py`, `tests/api_conftest.py`, `tests/test_api_encoder_migration.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a shared boot helper importable by `tests/test_api_encoder_migration.py` and Task 10.

**Explicitly out of scope — do not fix:** `tests/api_conftest.py:60` builds `TestClient(app)` *without* a context manager, so the shared `api` fixture never runs the ASGI lifespan. Fixing that would start the real scheduler singleton across the whole API suite. Leave it exactly as it is, and make sure your shared helper does not change it.

- [ ] **Step 1: Remove the fail-open import guard**

`tests/conftest.py:67-70` wraps `from transcoder import encoders` in `try/except ImportError: return`. The comment says "module does not exist yet in earlier tasks" — it exists now, so the branch is dead, and worse it fails *open*: a genuine `ImportError` inside `encoders.py` would be swallowed and the whole suite would silently shell out to a real HandBrakeCLI. Delete the try/except; import directly.

- [ ] **Step 2: Extract the shared boot helper**

`booted_api` in `tests/test_api_encoder_migration.py` duplicates ~12 monkeypatch lines from `api_conftest.py`. Move the shared setup into a function in `tests/api_conftest.py`, e.g.:

```python
def build_booted_client(monkeypatch, *, start_worker=False):
    """An app booted through the REAL ASGI lifespan, on a fresh in-memory DB.

    Distinct from the shared `api` fixture, which deliberately does not enter
    the TestClient context manager. Startup-ordering tests need the lifespan.
    Returns (client_context_manager, Session).
    """
```

Have `booted_api` call it. Do not alter the existing `api` fixture.

- [ ] **Step 3: Fix the three weak tests**

1. Delete the first test in `test_api_encoder_migration.py` — it is fully subsumed by the second (same setup, strictly weaker assertions). Confirm this by reading both before deleting.
2. The test asserting the literal `"H.265 NVENC 1080p"` gets that value from a config default, so a machine with `PRESET_1080` exported fails it confusingly. Add `monkeypatch.setattr(cfg, "PRESET_1080", "H.265 NVENC 1080p")` so the assertion is self-contained.
3. The `"auto"` default test cannot tell a config-sourced default from the schema literal — both are `"auto"`. Point `cfg.ENCODER_FAMILY` at a *different valid* family (e.g. `"cpu"`) and assert that value flows through, so the assertion has something to discriminate.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: green, count down by exactly 1 (the deleted subsumed test).

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 12: A real union type for encoder family ids

Closes: *family ids typed as open `string` rather than a union*.

**Files:**
- Modify: `solution/web/src/api/types.ts`, `solution/web/src/pages/Settings.tsx`, `solution/web/src/pages/Setup.tsx`, and the API client if it names the type
- Test: type-checking (`tsc -b`) is the test

**Interfaces:**
- Consumes: nothing.
- Produces: `export type EncoderFamilyId = "auto" | "vcn" | "nvenc" | "qsv" | "cpu" | "custom";`

**Naming constraint:** `EncoderFamily` is already an *interface* in `types.ts` (the catalog row: `id`, `label`, `preset_1080`, `preset_4k`, `hardware`, `available`). Do **not** rename it. The new union is `EncoderFamilyId`.

- [ ] **Step 1: Add the union and widen the interface**

```ts
export type EncoderFamilyId = "auto" | "vcn" | "nvenc" | "qsv" | "cpu" | "custom";

export interface EncoderFamily {
  id: EncoderFamilyId;
  // ... unchanged
}
```

- [ ] **Step 2: Thread it through**

Change `encoder_family: string` → `encoder_family: EncoderFamilyId` in the settings response interface, and `encoder_family?: string` → `encoder_family?: EncoderFamilyId` in `SettingsUpdate`. Then fix every resulting `tsc -b` error in `Settings.tsx` and `Setup.tsx` — typically the `useState<string>` holding the selection becomes `useState<EncoderFamilyId>`, and a `<select onChange>` needs `e.target.value as EncoderFamilyId`.

Prefer a narrowing helper over a bare cast where the value genuinely comes from outside:

```ts
const FAMILY_IDS: readonly EncoderFamilyId[] = ["auto", "vcn", "nvenc", "qsv", "cpu", "custom"];
export function asFamilyId(v: string): EncoderFamilyId {
  return (FAMILY_IDS as readonly string[]).includes(v) ? (v as EncoderFamilyId) : "auto";
}
```

- [ ] **Step 3: Typecheck**

Run: `cd solution/web && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Run the frontend suite**

Run: `cd solution/web && npm test`
Expected: 19 files, 76 tests, green.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 13: Select primitive test gaps

Closes: *`onChange` test asserts only that the handler fired, not the value*; *no test covers ref forwarding or className merging*.

**Files:**
- Test: `solution/web/src/components/ui/ui.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. **No production code changes** — unless a test reveals ref forwarding is genuinely broken, in which case stop and report rather than fixing it here.

- [ ] **Step 1: Strengthen the existing onChange assertion**

The test at `ui.test.tsx:21-33` ends with `expect(onChange).toHaveBeenCalled()`. Replace that with an assertion on the received value:

```ts
  fireEvent.change(el, { target: { value: "cpu" } });
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange.mock.calls[0][0].target.value).toBe("cpu");
```

- [ ] **Step 2: Add the two missing tests**

```tsx
test("Select forwards its ref to the underlying element", () => {
  const ref = React.createRef<HTMLSelectElement>();
  render(<Select ref={ref} aria-label="Encoder"><option value="cpu">CPU</option></Select>);
  expect(ref.current).toBeInstanceOf(HTMLSelectElement);
});

test("Select merges a caller className with its own", () => {
  render(<Select aria-label="Encoder" className="w-40"><option value="cpu">CPU</option></Select>);
  const el = screen.getByLabelText("Encoder");
  expect(el).toHaveClass("w-40");
  // and keeps at least one of the primitive's own classes
  expect(el.className.split(" ").length).toBeGreaterThan(1);
});
```

Import `React` if the file does not already.

- [ ] **Step 3: Run**

Run: `cd solution/web && npm test`
Expected: green, count up by 2.

- [ ] **Step 4: Report to the controller (do not commit)**

---

### Task 14: Setup wizard — no double-submit, no phantom family write

Closes: *"Save & continue" not disabled during an in-flight detect*; *wizard unconditionally writes `encoder_family: "auto"` even when Detect was never pressed*.

**Files:**
- Modify: `solution/web/src/pages/Setup.tsx`
- Test: `solution/web/src/pages/Setup.test.tsx`

**Interfaces:**
- Consumes: `EncoderFamilyId` from Task 12.
- Produces: nothing.

**Current behaviour** (`Setup.tsx:85-88`): `saveHandbrake` always sends `{ handbrake_cli, encoder_family: encFamily }`. When the user skips Detect, `encFamily` is `"auto"`, so the wizard writes an `encoder_family` row the user never chose. That is *usually* harmless — but it pre-empts `migrate_encoder_family`, whose whole job is to decide that value, including honouring `ENCODER_FAMILY` from `.env`. A user who configured `ENCODER_FAMILY=cpu` and clicked through the wizard silently loses it.

- [ ] **Step 1: Write the failing tests**

```tsx
test("Save & continue is disabled while detection is in flight", async () => {
  // make detectEncoders hang so the in-flight state is observable
  let resolveDetect: (v: unknown) => void = () => {};
  vi.mocked(detectEncoders).mockReturnValue(new Promise((r) => { resolveDetect = r; }) as never);
  // ... render, advance to the handbrake step, click Detect ...
  expect(screen.getByRole("button", { name: /save & continue/i })).toBeDisabled();
  resolveDetect({ ok: true, available: ["vcn", "cpu"], families: [], detected_at: "x" });
});

test("skipping detection does not write an encoder family", async () => {
  // ... render, advance to the handbrake step, type a path, click Save & continue
  //     WITHOUT clicking Detect ...
  expect(vi.mocked(updateSettings)).toHaveBeenCalledWith({ handbrake_cli: "C:/hb.exe" });
  // i.e. no encoder_family key at all -- the backend migration decides it
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd solution/web && npm test -- Setup`

- [ ] **Step 3: Implement**

1. Add `|| detecting` to the "Save & continue" button's `disabled` prop on the handbrake step (`Setup.tsx:159`).
2. Track whether the user actually established a family, and send the key only then:

```tsx
const [familyChosen, setFamilyChosen] = useState(false);
// set to true in detect() on a successful response, and in any explicit
// family picker the step offers

async function saveHandbrake() {
  const payload: SettingsUpdate = { handbrake_cli: handbrake };
  if (familyChosen) payload.encoder_family = encFamily;
  await updateSettings(payload);
  // ...
}
```

Keep the existing test "wizard saves the detected family with the CLI path" passing — after a successful Detect, `familyChosen` is true and both keys are sent.

- [ ] **Step 4: Run**

Run: `cd solution/web && npm test`
Expected: green, count up by 2.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 15: Setup wizard detection-branch coverage

Closes: *the "saves the detected family with the CLI path" test never asserts `handbrake_cli`*; *the no-hardware→cpu branch and the thrown-request branch are untested*.

**Files:**
- Test: `solution/web/src/pages/Setup.test.tsx`

**Interfaces:**
- Consumes: Task 14's changes must already be in the tree.
- Produces: nothing. **No production code changes.**

- [ ] **Step 1: Assert the CLI path in the existing test**

The test named "wizard saves the detected family with the CLI path" asserts the family but never `handbrake_cli` — a regression dropping it from the single-call payload would pass. Change the assertion to the full payload:

```tsx
expect(vi.mocked(updateSettings)).toHaveBeenCalledWith({
  handbrake_cli: "C:/hb/HandBrakeCLI.exe",
  encoder_family: "vcn",
});
```

- [ ] **Step 2: Add the no-hardware branch test**

```tsx
test("detection finding no hardware falls back to cpu", async () => {
  vi.mocked(detectEncoders).mockResolvedValue({
    ok: true, available: ["cpu"], detected_at: "2026-01-01T00:00:00Z", families: [],
  } as never);
  // ... render, advance, click Detect ...
  expect(await screen.findByText(/cpu/i)).toBeInTheDocument();
  // and the family that would be saved is "cpu", not "auto"
});
```

- [ ] **Step 3: Add the thrown-request test**

```tsx
test("a failed detection request surfaces an error and does not crash", async () => {
  vi.mocked(detectEncoders).mockRejectedValue(new Error("network down"));
  // ... render, advance, click Detect ...
  expect(await screen.findByText(/could not|failed|error/i)).toBeInTheDocument();
  // the Detect button is usable again
  expect(screen.getByRole("button", { name: /detect/i })).toBeEnabled();
});
```

Read `Setup.tsx:62-83` first and assert against the **actual** error text the catch branch renders into `encError`, not invented copy.

- [ ] **Step 4: Run**

Run: `cd solution/web && npm test`
Expected: green, count up by 2.

- [ ] **Step 5: Report to the controller (do not commit)**

---

### Task 16: Documentation corrections

Closes: *`CLAUDE.md:65` omits "Auto" from the family list*; *`CLAUDE.md:183` still says "HandBrake NVENC on the GPU"*; *`.env.example:19` references `PRESET_1080`/`PRESET_4K`, neither of which appears in that file*.

**Files:**
- Modify: `CLAUDE.md`, `.env.example`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. **No code changes; no tests.**

- [ ] **Step 1: `CLAUDE.md` — add Auto to the Settings family list**

Around line 65 the Settings screen is described as offering "(AMD VCN / NVIDIA NVENC / Intel QSV / CPU x265 / Custom)". `Auto` is the first and default option and is missing. Change to:

`(Auto / AMD VCN / NVIDIA NVENC / Intel QSV / CPU x265 / Custom)`

- [ ] **Step 2: `CLAUDE.md` — fix the Deploy section**

Around line 183 the Deploy paragraph says the app "runs natively (HandBrake NVENC on the GPU, in the user's session)". That contradicts the encoder-family table earlier in the same file. Change the parenthetical to:

`(HandBrake hardware encoding on the GPU — AMD VCN, NVIDIA NVENC or Intel QSV — in the user's session)`

- [ ] **Step 3: `.env.example` — reconcile the preset comment**

Line 19 references `PRESET_1080` / `PRESET_4K`, but neither variable appears anywhere in the file. Either add both with their current defaults, or reword the comment to point at the encoder-family setting. Prefer **adding** them, documented as custom-only, plus `ENCODER_FAMILY`:

```
# Encoder family: auto | vcn | nvenc | qsv | cpu | custom  (default: auto)
# 'auto' detects your hardware. Set explicitly only to override detection.
ENCODER_FAMILY=auto

# Used ONLY when ENCODER_FAMILY=custom. Ignored for every other family, which
# picks its presets from the built-in catalog.
#PRESET_1080=H.265 NVENC 1080p
#PRESET_4K=H.265 NVENC 2160p 4K
```

Read the file first and match its existing comment style and section order.

- [ ] **Step 4: Verify nothing else claims NVIDIA is required**

Run: `grep -rn -i "nvenc\|nvidia" CLAUDE.md .env.example README.md deploy/h265-transcoder/README.md`
Every remaining hit must be either a legitimate mention of NVENC *as one option among several*, or a preset name. Report any that are not; do not edit `README.md` or the deploy README (they were corrected on the previous branch) unless you find a genuine contradiction, and say so in your report if you do.

- [ ] **Step 5: Report to the controller (do not commit)**

---

## Self-Review

**1. Coverage of the 33 findings.** Every finding maps to a task: Task 1 → 3, Task 2 → 2, Task 3 → 1, Task 4 → 1, Task 5 → 4, Task 6 → 1, Task 7 → 1, Task 8 → 2, Task 9 → 1, Task 10 → 1, Task 11 → 5, Task 12 → 1, Task 13 → 2, Task 14 → 2, Task 15 → 3, Task 16 → 3. Total **33**.

**2. Placeholder scan.** No "TBD", no "add appropriate error handling", no "similar to Task N". Task 5 Step 3 and Task 11 Step 3.1 direct the worker to *read and judge* (which tests are subsumed) rather than giving literal code — this is deliberate and bounded: both require the worker to justify each deletion in its report, and the suite count is pinned in Step 4 so an over-deletion is caught.

**3. Type consistency.** `reset_probe_cache()` is defined in Task 4 and consumed in Task 9 under the same name. `EncoderFamilyId` is defined in Task 12 and consumed in Task 14 under the same name, and is deliberately distinct from the pre-existing `EncoderFamily` interface. `build_booted_client` is defined in Task 11 and referenced by Task 10, which is ordered in an earlier wave — Task 10 therefore says to inline the setup if the helper is absent and flag it.

**4. Known risk.** Task 6's dynamically-built `Literal` may not satisfy pydantic; the task carries an explicit fallback with a drift-guard test.

**5. Invariant check.** No task weakens "unknown is not unavailable". Task 2 makes malformed input read as unknown (safer). Task 4 memoises unknown only in memory. Task 3 substitutes CPU only where the alternative is an invalid empty preset, and marks it `substituted=True` so it is logged.
