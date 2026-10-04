# Arr Import Revision Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transcoded files that came from a Proper/Repack/Real release get re-imported by Radarr/Sonarr automatically, and a re-import that is *not* accepted fails the job visibly instead of reporting `done`.

**Architecture:** A new shared module `transcoder/arr_import.py` owns two pure concerns used by both clients: rendering a quality object (name + revision tokens) into the filename quality string, and choosing the import candidate (raising `ImportNotQueued` with Radarr/Sonarr's own rejection reasons). Discovery already stores `quality` on every scan and `_output_name()` already embeds it, so fixing the quality string fixes the filename with no schema change. The worker's existing `except Exception` branch turns `ImportNotQueued` into a `failed` job; it needs no code change, only a test that pins the behavior.

**Tech Stack:** Python 3, requests, SQLAlchemy, pytest (monkeypatch).

**Spec:** this document (the investigation in the 2026-10-04 session is summarized under *Evidence*).

## Evidence (why)

- `The Long Walk - Se ti fermi muori` (Radarr movie 696) was transcoded 13 times between 2026-09-20 and 2026-10-04; every job reported `done`, but Radarr kept `…Bluray-1080p Proper x264.mkv` until a manual import.
- `api.log`: `Radarr did not recognise /downloads/The Long Walk … Bluray-1080p Release-OPO.mkv`. `manual_import_one` drops candidates with `rejections` and swallows every exception.
- Radarr `/api/v3/parse`: original → `Bluray-1080p` revision **v2**; our output name → revision **v1**. A lower revision is rejected as a non-upgrade. `_output_name()` builds from `item.quality`, which holds only `quality.quality.name`.
- Revision tokens probed against the live Radarr and Sonarr parsers (2026-10-04):

| token | Radarr | Sonarr |
|---|---|---|
| *(none)* | v1 | v1 |
| `Proper` | v2 | v2 |
| `REPACK` | v2, isRepack | v2, isRepack |
| `REPACK2` | v3, isRepack | v3, isRepack |
| `v3` | **v1** | v3 |
| `REAL` | real 1 | real 1 |
| `REAL Proper` | v2, real 1 | v2, real 1 |

  So: v2 → `Proper` (or `REPACK` when `isRepack`); vN≥3 → `REPACK{N-1}` (the only token both parsers read as ≥v3); `real` → `REAL` per count, placed first.

## Global Constraints

- Use TDD: write the failing test, then implement (CLAUDE.md).
- Backend suite: `python -m pytest` from the repo root (not `cd solution`).
- No schema migration. `media_item.quality` stays a free-form `String(128)`.
- Exception messages name the app (`Radarr` / `Sonarr`) and quote the app's rejection `reason` strings verbatim.
- Workers must not run `git commit`, `checkout`, `restore`, `stash`, `reset`, or `clean`. The orchestrator commits each task as it lands.

## Review Focus

1. **Quality object with no `revision` key, or `revision: null`** (older Radarr/Sonarr builds, test doubles) → plain quality name, no tokens. Pinned in Task 1.
2. **Missing or `null` `quality` on a movie file** → `"Unknown Quality"` instead of an `AttributeError` that aborts the whole Radarr scan. Today `movie_file.get("quality").get(...)` crashes; pinned in Task 2.
3. **Candidate path differs only in case or slash direction from the mapped path** → still matched, as today (`os.path.normcase`). Pinned in Task 1.
4. **Matching candidate with several rejections** → every reason appears in the job's `error_message`, joined with `; `. Pinned in Task 1.
5. **Network error or HTTP 4xx/5xx from `manualimport` / `command`** → `ImportNotQueued` naming the app, so the job fails rather than reporting `done`. Pinned in Tasks 3 and 4.

Known and out of scope: a file that is still rejected for some other reason (for example a quality cutoff) leaves the item at `needs_transcode`, so it is re-transcoded on each scheduled run. After this plan that loop shows up as failed jobs carrying the reason, not hidden `done` jobs. The `_source_file_missing` misclassification (`Errno 22`/`28`) is a separate follow-up.

---

### Task 1: Shared import helpers

**Files:**
- Create: `solution/transcoder/arr_import.py`
- Test: `tests/test_arr_import.py`

**Interfaces:**
- Produces:
  - `class ImportNotQueued(RuntimeError)`
  - `release_quality(quality: dict | None) -> str` (e.g. `"Bluray-1080p Proper"`)
  - `pick_candidate(candidates: list[dict], path: str, app: str) -> dict`, which raises `ImportNotQueued`

- [ ] **Step 1: Write the failing tests** — `tests/test_arr_import.py`:

```python
import pytest

from transcoder.arr_import import ImportNotQueued, pick_candidate, release_quality


def _q(name="Bluray-1080p", **revision):
    q = {"quality": {"name": name, "resolution": 1080}}
    if revision:
        q["revision"] = revision
    return q


@pytest.mark.parametrize("revision, expected", [
    ({"version": 1, "real": 0, "isRepack": False}, "Bluray-1080p"),
    ({"version": 2, "real": 0, "isRepack": False}, "Bluray-1080p Proper"),
    ({"version": 2, "real": 0, "isRepack": True}, "Bluray-1080p REPACK"),
    ({"version": 3, "real": 0, "isRepack": False}, "Bluray-1080p REPACK2"),
    ({"version": 4, "real": 0, "isRepack": True}, "Bluray-1080p REPACK3"),
    ({"version": 1, "real": 1, "isRepack": False}, "Bluray-1080p REAL"),
    ({"version": 2, "real": 1, "isRepack": False}, "Bluray-1080p REAL Proper"),
])
def test_release_quality_renders_revision_tokens(revision, expected):
    assert release_quality(_q(**revision)) == expected


def test_release_quality_without_revision_is_plain_name():
    assert release_quality(_q()) == "Bluray-1080p"
    assert release_quality({"quality": {"name": "HDTV-720p"}, "revision": None}) == "HDTV-720p"


def test_release_quality_missing_quality_is_unknown():
    assert release_quality(None) == "Unknown Quality"
    assert release_quality({}) == "Unknown Quality"


def test_pick_candidate_returns_unrejected_match_ignoring_case_and_slashes():
    good = {"path": "/downloads/Movie (2025).mkv", "rejections": []}
    other = {"path": "/downloads/Other.mkv", "rejections": []}
    assert pick_candidate([other, good], "/Downloads/movie (2025).mkv", "Radarr") is good


def test_pick_candidate_raises_with_all_rejection_reasons():
    rejected = {"path": "/downloads/M.mkv", "rejections": [
        {"reason": "Not an upgrade for existing movie file(s)", "type": "permanent"},
        {"reason": "Sample", "type": "permanent"},
    ]}
    with pytest.raises(ImportNotQueued) as exc:
        pick_candidate([rejected], "/downloads/M.mkv", "Radarr")
    msg = str(exc.value)
    assert msg.startswith("Radarr rejected /downloads/M.mkv: ")
    assert "Not an upgrade for existing movie file(s); Sample" in msg


def test_pick_candidate_raises_when_path_not_listed():
    with pytest.raises(ImportNotQueued, match="Sonarr did not find /downloads/E.mkv"):
        pick_candidate([{"path": "/downloads/X.mkv", "rejections": []}], "/downloads/E.mkv", "Sonarr")


def test_import_not_queued_is_a_runtime_error():
    assert issubclass(ImportNotQueued, RuntimeError)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python -m pytest tests/test_arr_import.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'transcoder.arr_import'`.

- [ ] **Step 3: Implement** `solution/transcoder/arr_import.py`:

```python
"""Helpers shared by the Sonarr and Radarr clients for getting a transcoded
file re-imported in place of the original."""
import os


class ImportNotQueued(RuntimeError):
    """Sonarr/Radarr did not accept the uploaded file for import."""


def _revision_tokens(revision: dict | None) -> list[str]:
    # Tokens chosen so BOTH parsers read back the same revision (verified
    # against live Radarr/Sonarr /api/v3/parse): "v3" only works in Sonarr,
    # while "REPACK<n>" means version n+1 in both. Without the tokens the
    # output parses as v1 and is rejected as a downgrade of a Proper source.
    rev = revision or {}
    version = int(rev.get("version") or 1)
    tokens = ["REAL"] * int(rev.get("real") or 0)
    if version == 2:
        tokens.append("REPACK" if rev.get("isRepack") else "Proper")
    elif version >= 3:
        tokens.append(f"REPACK{version - 1}")
    return tokens


def release_quality(quality: dict | None) -> str:
    """Render a Sonarr/Radarr quality object as the filename quality string,
    e.g. ``{"quality": {"name": "Bluray-1080p"}, "revision": {"version": 2}}``
    -> ``"Bluray-1080p Proper"``."""
    q = quality or {}
    name = (q.get("quality") or {}).get("name") or "Unknown Quality"
    return " ".join([name, *_revision_tokens(q.get("revision"))])


def pick_candidate(candidates: list[dict], path: str, app: str) -> dict:
    """Return the manual-import candidate for ``path``; raise ImportNotQueued
    carrying the app's own rejection reasons when it will not import it."""
    target = os.path.normcase(path)
    matches = [c for c in candidates if os.path.normcase(c.get("path", "")) == target]
    if not matches:
        raise ImportNotQueued(f"{app} did not find {path} in its import folder")
    for c in matches:
        if not c.get("rejections"):
            return c
    reasons = "; ".join(
        r.get("reason", "unknown") for c in matches for r in c.get("rejections") or []
    )
    raise ImportNotQueued(f"{app} rejected {path}: {reasons}")
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_arr_import.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit** (orchestrator)

```bash
git add solution/transcoder/arr_import.py tests/test_arr_import.py
git commit -m "feat: add shared arr import helpers (revision-aware quality, candidate picking)"
```

---

### Task 2: Discovery stores the revision-aware quality

**Files:**
- Modify: `solution/transcoder/sonarr_client.py:115-118` (`extract_quality`)
- Modify: `solution/transcoder/radarr_client.py:43-44` (`filter_non_h265_movies`)
- Test: `tests/test_arr_quality_extract.py`

**Interfaces:**
- Consumes: `release_quality(quality: dict | None) -> str` from Task 1.
- Produces: `SonarrClient.extract_quality(ef)` and each row's `"quality"` from `RadarrClient.filter_non_h265_movies` now include revision tokens. The signatures are unchanged.

- [ ] **Step 1: Write the failing tests** — `tests/test_arr_quality_extract.py`:

```python
from transcoder.radarr_client import RadarrClient
from transcoder.sonarr_client import SonarrClient


def test_sonarr_extract_quality_keeps_proper():
    ef = {"quality": {"quality": {"name": "WEBDL-1080p", "resolution": 1080},
                      "revision": {"version": 2, "real": 0, "isRepack": False}}}
    assert SonarrClient.extract_quality(ef) == "WEBDL-1080p Proper"


def test_sonarr_extract_quality_without_quality_is_unknown():
    assert SonarrClient.extract_quality({}) == "Unknown Quality"


def _movie(quality):
    return {"id": 696, "title": "The Long Walk", "year": 2025, "movieFile": {
        "id": 2749, "path": "/movies/x.mkv", "mediaInfo": {"videoCodec": "x264"},
        "languages": [{"name": "Italian"}], "quality": quality,
    }}


def test_radarr_quality_keeps_proper():
    q = {"quality": {"name": "Bluray-1080p", "resolution": 1080},
         "revision": {"version": 2, "real": 0, "isRepack": False}}
    rows = RadarrClient("http://r", "k").filter_non_h265_movies([_movie(q)])
    assert rows[0]["quality"] == "Bluray-1080p Proper"
    assert rows[0]["resolution"] == 1080


def test_radarr_missing_quality_does_not_crash_scan():
    rows = RadarrClient("http://r", "k").filter_non_h265_movies([_movie(None)])
    assert rows[0]["quality"] == "Unknown Quality"
    assert rows[0]["resolution"] is None
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python -m pytest tests/test_arr_quality_extract.py -v`
Expected: FAIL. The Proper tests return the bare name, and the missing-quality Radarr test raises `AttributeError: 'NoneType' object has no attribute 'get'`.

- [ ] **Step 3: Implement**

`sonarr_client.py` — add `from transcoder.arr_import import release_quality` next to the other `transcoder` imports, and replace `extract_quality`'s body:

```python
    @staticmethod
    def extract_quality(episode_file: dict) -> str:
        """Quality name plus revision tokens (e.g. 'WEBDL-1080p Proper')."""
        return release_quality(episode_file.get("quality"))
```

`radarr_client.py` — add the same import, then in `filter_non_h265_movies` replace the two `movie_file.get("quality")...` lines with:

```python
                    "resolution": ((movie_file.get("quality") or {}).get("quality") or {}).get("resolution"),
                    "quality": release_quality(movie_file.get("quality")),
```

(Discovery already does `resolution = r["resolution"] or 0`, so `None` is safe.)

- [ ] **Step 4: Run the tests and confirm they pass, plus the discovery suite**

Run: `python -m pytest tests/test_arr_quality_extract.py tests/test_discovery.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit** (orchestrator)

```bash
git add solution/transcoder/sonarr_client.py solution/transcoder/radarr_client.py tests/test_arr_quality_extract.py
git commit -m "fix: keep Proper/Repack revision in discovered quality so re-imports are not downgrades"
```

---

### Task 3: Radarr manual import reports failure

**Files:**
- Modify: `solution/transcoder/radarr_client.py:58-110` (`manual_import_one`)
- Test: `tests/test_radarr_manual_import.py`

**Interfaces:**
- Consumes: `ImportNotQueued` and `pick_candidate(candidates, path, app)` from Task 1.
- Produces: `RadarrClient.manual_import_one(full_path_host: str) -> None` now **raises `ImportNotQueued`** whenever the import was not queued. It no longer swallows errors.

- [ ] **Step 1: Write the failing tests** — `tests/test_radarr_manual_import.py`:

```python
import pytest
import requests

from transcoder import radarr_client
from transcoder.arr_import import ImportNotQueued
from transcoder.radarr_client import RadarrClient

PATH = "/downloads/M (2025) [h265] Bluray-1080p Proper Release-OPO.mkv"


class _Resp:
    def __init__(self, payload=None, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


@pytest.fixture
def http(monkeypatch):
    calls = {"post": []}
    monkeypatch.setattr(radarr_client.settings, "DOCKER_HOST_ROOT", "./out/")
    monkeypatch.setattr(radarr_client.settings, "DOCKER_DOCKER_ROOT", "/downloads/")

    def install(get_payload, get_status=200, post_status=201):
        monkeypatch.setattr(radarr_client.requests, "get",
                            lambda *a, **k: _Resp(get_payload, get_status))

        def post(url, **kw):
            calls["post"].append(kw["json"])
            return _Resp({}, post_status)
        monkeypatch.setattr(radarr_client.requests, "post", post)
        return calls
    return install


def _cand(rejections=()):
    return {"path": PATH, "movie": {"id": 696}, "quality": {"q": 1},
            "languages": [], "releaseGroup": "OPO", "indexerFlags": 0,
            "rejections": list(rejections)}


def test_queues_import_for_accepted_candidate(http):
    calls = http([_cand()])
    RadarrClient("http://r", "k").manual_import_one("./out/" + PATH.split("/")[-1])
    assert calls["post"][0]["name"] == "ManualImport"
    assert calls["post"][0]["files"][0]["movieId"] == 696


def test_rejected_candidate_raises_with_reason(http):
    calls = http([_cand([{"reason": "Not an upgrade for existing movie file(s)"}])])
    with pytest.raises(ImportNotQueued, match="Radarr rejected .*Not an upgrade"):
        RadarrClient("http://r", "k").manual_import_one("./out/" + PATH.split("/")[-1])
    assert calls["post"] == []


def test_missing_candidate_raises(http):
    http([])
    with pytest.raises(ImportNotQueued, match="Radarr did not find"):
        RadarrClient("http://r", "k").manual_import_one("./out/" + PATH.split("/")[-1])


def test_http_error_raises_import_not_queued(http):
    http([_cand()], post_status=500)
    with pytest.raises(ImportNotQueued, match="Radarr manual import failed"):
        RadarrClient("http://r", "k").manual_import_one("./out/" + PATH.split("/")[-1])
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python -m pytest tests/test_radarr_manual_import.py -v`
Expected: the first test PASSES (behavior is unchanged), and the three `raises` tests FAIL with `DID NOT RAISE`.

- [ ] **Step 3: Implement** — in `radarr_client.py`, add `from transcoder.arr_import import ImportNotQueued, pick_candidate` (next to the Task 2 import, which can share the line), then replace the body of `manual_import_one` from `try:` to the end with:

```python
        try:
            folder = os.path.dirname(radarr_path)
            r1 = requests.get(
                f"{self.url}/api/v3/manualimport",
                headers=self.headers,
                params={"folder": folder, "filterExistingFiles": "true"},
                timeout=30,
            )
            r1.raise_for_status()
            info = pick_candidate(r1.json(), radarr_path, "Radarr")
            payload = {
                "name": "ManualImport",
                "importMode": "Move",
                "files": [{
                    "path": info["path"],
                    "movieId": info["movie"]["id"],
                    "quality": info.get("quality"),
                    "languages": info.get("languages"),
                    "releaseGroup": info.get("releaseGroup"),
                    "indexerFlags": info.get("indexerFlags"),
                }]
            }
            r2 = requests.post(
                f"{self.url}/api/v3/command",
                headers={**self.headers, "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            r2.raise_for_status()
            log.info("Manual-import queued for %s", info['path'])
        except ImportNotQueued:
            raise
        except Exception as exc:
            raise ImportNotQueued(
                f"Radarr manual import failed for {radarr_path}: {exc}"
            ) from exc
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_radarr_manual_import.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit** (orchestrator)

```bash
git add solution/transcoder/radarr_client.py tests/test_radarr_manual_import.py
git commit -m "fix: surface Radarr manual-import rejections instead of swallowing them"
```

---

### Task 4: Sonarr manual import reports failure

**Files:**
- Modify: `solution/transcoder/sonarr_client.py:133-195` (`manual_import_one`)
- Test: `tests/test_sonarr_manual_import.py`

**Interfaces:**
- Consumes: `ImportNotQueued` and `pick_candidate(candidates, path, app)` from Task 1.
- Produces: `SonarrClient.manual_import_one(full_path_host: str) -> None` now **raises `ImportNotQueued`** whenever the import was not queued.

- [ ] **Step 1: Write the failing tests** — `tests/test_sonarr_manual_import.py`:

```python
import pytest
import requests

from transcoder import sonarr_client
from transcoder.arr_import import ImportNotQueued
from transcoder.sonarr_client import SonarrClient

NAME = "Slow Horses - S06E02 - h265 - [ENGLISH] WEBDL-1080p Proper Release-OPO.mkv"
PATH = "/downloads/" + NAME


class _Resp:
    def __init__(self, payload=None, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


@pytest.fixture
def http(monkeypatch):
    calls = {"post": []}
    monkeypatch.setattr(sonarr_client.settings, "DOCKER_HOST_ROOT", "./out/")
    monkeypatch.setattr(sonarr_client.settings, "DOCKER_DOCKER_ROOT", "/downloads/")

    def install(get_payload, get_status=200, post_status=201):
        monkeypatch.setattr(sonarr_client.requests, "get",
                            lambda *a, **k: _Resp(get_payload, get_status))

        def post(url, **kw):
            calls["post"].append(kw["json"])
            return _Resp({}, post_status)
        monkeypatch.setattr(sonarr_client.requests, "post", post)
        return calls
    return install


def _cand(rejections=()):
    return {"path": PATH, "series": {"id": 7}, "episodes": [{"id": 70}, {"id": 71}],
            "quality": {"q": 1}, "languages": [], "releaseGroup": "OPO",
            "indexerFlags": 0, "rejections": list(rejections)}


def test_queues_import_for_accepted_candidate(http):
    calls = http([_cand()])
    SonarrClient("http://s", "k").manual_import_one("./out/" + NAME)
    files = calls["post"][0]["files"][0]
    assert files["seriesId"] == 7 and files["episodeIds"] == [70, 71]


def test_rejected_candidate_raises_with_reason(http):
    calls = http([_cand([{"reason": "Not an upgrade for existing episode file(s)"}])])
    with pytest.raises(ImportNotQueued, match="Sonarr rejected .*Not an upgrade"):
        SonarrClient("http://s", "k").manual_import_one("./out/" + NAME)
    assert calls["post"] == []


def test_missing_candidate_raises(http):
    http([])
    with pytest.raises(ImportNotQueued, match="Sonarr did not find"):
        SonarrClient("http://s", "k").manual_import_one("./out/" + NAME)


def test_http_error_raises_import_not_queued(http):
    http([_cand()], get_status=503)
    with pytest.raises(ImportNotQueued, match="Sonarr manual import failed"):
        SonarrClient("http://s", "k").manual_import_one("./out/" + NAME)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python -m pytest tests/test_sonarr_manual_import.py -v`
Expected: the first test PASSES, and the three `raises` tests FAIL with `DID NOT RAISE`.

- [ ] **Step 3: Implement** — in `sonarr_client.py`, add `from transcoder.arr_import import ImportNotQueued, pick_candidate` (next to the Task 2 import), then replace the body of `manual_import_one` from `try:` to the end with:

```python
        try:
            folder = os.path.dirname(sonarr_path)
            # 1️⃣ List import candidates
            r1 = requests.get(
                f"{self.url}/api/v3/manualimport",
                headers=self.headers,
                params={"folder": folder, "filterExistingFiles": "true"},
                timeout=30,
            )
            r1.raise_for_status()
            info = pick_candidate(r1.json(), sonarr_path, "Sonarr")
            payload = {
                "name": "ManualImport",
                "importMode": "Move",
                "files": [{
                    "path": info["path"],
                    "seriesId": info["series"]["id"],
                    "episodeIds": [e["id"] for e in info["episodes"]],
                    "quality": info.get("quality"),
                    "languages": info.get("languages"),
                    "releaseGroup": info.get("releaseGroup"),
                    "indexerFlags": info.get("indexerFlags"),
                }]
            }

            # 2️⃣ Queue the import
            r2 = requests.post(
                f"{self.url}/api/v3/command",
                headers={**self.headers, "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            r2.raise_for_status()
            log.info("Manual-import queued for %s", info['path'])
        except ImportNotQueued:
            raise
        except Exception as exc:
            raise ImportNotQueued(
                f"Sonarr manual import failed for {sonarr_path}: {exc}"
            ) from exc
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_sonarr_manual_import.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit** (orchestrator)

```bash
git add solution/transcoder/sonarr_client.py tests/test_sonarr_manual_import.py
git commit -m "fix: surface Sonarr manual-import rejections instead of swallowing them"
```

---

### Task 5: Worker records a rejected import as a failed job

**Files:**
- Test: `tests/test_worker_import_rejected.py`
- Modify: `solution/transcoder/engine/worker.py`, but only if Step 2 fails (no change is expected; the existing `except Exception` branch at `worker.py:232` already records the failure).

**Interfaces:**
- Consumes: `ImportNotQueued` from Task 1; `process_one_job(session, job, clients, *, download, upload, convert)`.

- [ ] **Step 1: Write the test** — `tests/test_worker_import_rejected.py`:

```python
import os

from transcoder.arr_import import ImportNotQueued
from transcoder.engine.worker import process_one_job
from transcoder.models import Job, MediaItem


class RejectingClient:
    def manual_import_one(self, path):
        raise ImportNotQueued("Radarr rejected /downloads/M.mkv: Not an upgrade for existing movie file(s)")


def test_rejected_import_fails_job_and_keeps_item_eligible(session, monkeypatch):
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000 if "tmp" in p else 400)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)

    item = MediaItem(source="radarr", external_id="2749", title="M", year=2025,
                     remote_path="/movies/M.mkv", resolution=1080,
                     quality="Bluray-1080p Proper", languages="ENG",
                     eligibility="needs_transcode")
    session.add(item)
    session.commit()
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()

    def download(host, port, user, pw, remote, local, progress_cb=None):
        return {"success": True}

    def upload(host, port, user, pw, local, remote, progress_cb=None):
        return {"success": True}

    def convert(tmp, out_name, preset, progress_cb=None, cancel_event=None, handbrake_cli=None):
        return ("./out/" + out_name, False)

    process_one_job(session, job, {"radarr": RejectingClient()},
                    download=download, upload=upload, convert=convert)

    assert job.state == "failed"
    assert "Not an upgrade" in job.error_message
    assert job.output_filename is None
    assert item.eligibility == "needs_transcode"   # not falsely marked already_h265
    assert "Bluray-1080p Proper Release-" in job.log  # Proper reached the uploaded filename
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_worker_import_rejected.py -v`
Expected: PASS without any worker change. If it fails, fix `worker.py` so the exception from `client.manual_import_one` reaches the `except Exception` branch before `item.eligibility`/`job.state = "done"` are set, then re-run.

- [ ] **Step 3: Full backend suite**

Run: `python -m pytest`
Expected: all PASS.

- [ ] **Step 4: Commit** (orchestrator)

```bash
git add tests/test_worker_import_rejected.py
git commit -m "test: pin that a rejected re-import fails the job instead of reporting done"
```

---

## Execution waves

- **Wave 1:** Task 1.
- **Wave 2:** Tasks 2, 3 and 4 all touch `radarr_client.py` and/or `sonarr_client.py`, so they run **sequentially**: Task 2, then 3, then 4. Task 5 can run in parallel with them because it only adds a test file.
- After each task: review by Opus, then commit. After the last one: run the full suite, then `/ship`. No frontend files change, so the Vitest suite is unaffected; run it anyway before shipping.
