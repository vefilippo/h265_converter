# Sonarr/Radarr Webhook Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Sonarr/Radarr POST a webhook on import so the app instantly discovers + enqueues just that one series/movie for transcoding, instead of waiting for a scheduled or manual scan.

**Architecture:** A new *open* FastAPI router (`api/routers/webhook.py`) handles `POST /api/webhook/{source}`. It self-authenticates with HTTP Basic against credentials in the `setting` table (it can't use the session-cookie `require_auth` the other routers share), returns `200` immediately, and runs a targeted `discover_* → enqueue_eligible → controller.wake()` in a `BackgroundTasks` job. An in-memory coalescer collapses burst webhooks for the same title. Credentials are managed from a new "Webhooks" section on the existing Settings page.

**Tech Stack:** Python / FastAPI / SQLAlchemy / pydantic (backend); React + TanStack Query + Tailwind (frontend); pytest (backend tests); vitest + Testing Library (frontend tests). `bcrypt` (already a dependency) for password hashing.

---

## Reference: how Sonarr/Radarr webhook payloads look

Both apps send JSON with an `eventType`. The import event is `"Download"`. The Test button sends `"Test"`. Relevant shapes:

```json
// Sonarr "Download" (on import)
{ "eventType": "Download", "series": { "id": 7, "title": "Breaking Bad" },
  "episodes": [ { "seasonNumber": 1, "episodeNumber": 2 } ], "isUpgrade": false }

// Radarr "Download" (on import)
{ "eventType": "Download", "movie": { "id": 3, "title": "Inception", "year": 2010 },
  "isUpgrade": false }
```

So the title lives at `series.title` (Sonarr) and `movie.title` (Radarr).

## File structure

- **Create** `source_code/transcoder/api/routers/webhook.py` — the webhook router: payload parsing, Basic-auth verification, the endpoint, and the background processor + coalescer.
- **Create** `source_code/tests/test_api_webhook.py` — backend tests for parsing, auth, the endpoint, and the coalescer.
- **Modify** `source_code/transcoder/api/app.py` — register the webhook router *without* `require_auth`.
- **Modify** `source_code/transcoder/api/schemas.py` — add webhook fields to `SettingsOut` / `SettingsUpdate`.
- **Modify** `source_code/transcoder/api/routers/settings.py` — read/write the webhook credentials.
- **Create** `source_code/tests/test_api_settings_webhook.py` — backend tests for the settings plumbing.
- **Modify** `source_code/web/src/api/types.ts` — add webhook fields to `Settings` / `SettingsUpdate`.
- **Modify** `source_code/web/src/pages/Settings.tsx` — add the "Webhooks" section.
- **Create** `source_code/web/src/pages/Settings.test.tsx` — frontend test for the section.
- **Modify** `CLAUDE.md` — document the new endpoint.

---

## Task 1: Payload title extraction (pure helper)

**Files:**
- Create: `source_code/transcoder/api/routers/webhook.py`
- Test: `source_code/tests/test_api_webhook.py`

- [ ] **Step 1: Write the failing test**

Create `source_code/tests/test_api_webhook.py`:

```python
from transcoder.api.routers.webhook import extract_title


def test_extract_title_sonarr():
    payload = {"eventType": "Download", "series": {"title": "Breaking Bad"}}
    assert extract_title("sonarr", payload) == "Breaking Bad"


def test_extract_title_radarr():
    payload = {"eventType": "Download", "movie": {"title": "Inception", "year": 2010}}
    assert extract_title("radarr", payload) == "Inception"


def test_extract_title_missing_returns_none():
    assert extract_title("sonarr", {"eventType": "Test"}) is None
    assert extract_title("radarr", {"movie": {}}) is None
    assert extract_title("sonarr", {"series": None}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && python -m pytest tests/test_api_webhook.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'extract_title'`.

- [ ] **Step 3: Write minimal implementation**

Create `source_code/transcoder/api/routers/webhook.py`:

```python
import logging

log = logging.getLogger("transcoder")


def extract_title(source: str, payload: dict) -> str | None:
    """Pull the series/movie title out of a Sonarr/Radarr webhook payload.

    Returns None when the expected object is absent (e.g. a Test event)."""
    if source == "sonarr":
        return (payload.get("series") or {}).get("title")
    if source == "radarr":
        return (payload.get("movie") or {}).get("title")
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && python -m pytest tests/test_api_webhook.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/api/routers/webhook.py source_code/tests/test_api_webhook.py
git commit -m "feat(webhook): payload title extraction helper"
```

---

## Task 2: HTTP Basic auth verification

**Files:**
- Modify: `source_code/transcoder/api/routers/webhook.py`
- Test: `source_code/tests/test_api_webhook.py`

- [ ] **Step 1: Write the failing test**

Append to `source_code/tests/test_api_webhook.py`:

```python
import base64
import bcrypt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import transcoder.api.routers.webhook as webhook


def _make_request(auth_header: str | None) -> Request:
    headers = []
    if auth_header is not None:
        headers.append((b"authorization", auth_header.encode()))
    scope = {"type": "http", "headers": headers}
    return Request(scope)


def _basic(user: str, pw: str) -> str:
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return f"Basic {token}"


def _seed_creds(monkeypatch, user="hookuser", pw="hookpass"):
    pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    store = {"webhook_username": user, "webhook_password_hash": pw_hash}
    monkeypatch.setattr(webhook, "_load_creds", lambda: (store["webhook_username"], store["webhook_password_hash"]))


def test_verify_auth_accepts_valid(monkeypatch):
    _seed_creds(monkeypatch)
    # Should not raise.
    webhook.verify_webhook_auth(_make_request(_basic("hookuser", "hookpass")))


def test_verify_auth_rejects_wrong_password(monkeypatch):
    _seed_creds(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        webhook.verify_webhook_auth(_make_request(_basic("hookuser", "WRONG")))
    assert exc.value.status_code == 401


def test_verify_auth_rejects_missing_header(monkeypatch):
    _seed_creds(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        webhook.verify_webhook_auth(_make_request(None))
    assert exc.value.status_code == 401
    assert exc.value.headers.get("WWW-Authenticate") == "Basic"


def test_verify_auth_rejects_when_not_configured(monkeypatch):
    monkeypatch.setattr(webhook, "_load_creds", lambda: (None, None))
    with pytest.raises(HTTPException) as exc:
        webhook.verify_webhook_auth(_make_request(_basic("hookuser", "hookpass")))
    assert exc.value.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && python -m pytest tests/test_api_webhook.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_load_creds'` / `verify_webhook_auth`.

- [ ] **Step 3: Write minimal implementation**

Add to `source_code/transcoder/api/routers/webhook.py` (imports at top, functions below `extract_title`):

```python
import base64
import binascii
import hmac

import bcrypt
from fastapi import HTTPException, Request

from transcoder.db import SessionLocal
from transcoder.repo import get_setting

_UNAUTH = {"WWW-Authenticate": "Basic"}


def _load_creds() -> tuple[str | None, str | None]:
    """Read the configured webhook username + bcrypt password hash."""
    with SessionLocal() as db:
        return (
            get_setting(db, "webhook_username"),
            get_setting(db, "webhook_password_hash"),
        )


def verify_webhook_auth(request: Request) -> None:
    """Enforce HTTP Basic auth against the stored webhook credentials.

    Raises 401 (with a WWW-Authenticate header) on any failure."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        raise HTTPException(401, "authentication required", headers=_UNAUTH)
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise HTTPException(401, "authentication required", headers=_UNAUTH)
    username, _, password = decoded.partition(":")

    stored_user, stored_hash = _load_creds()
    if not stored_user or not stored_hash:
        raise HTTPException(401, "webhook auth not configured", headers=_UNAUTH)

    user_ok = hmac.compare_digest(username, stored_user)
    pass_ok = bcrypt.checkpw(password.encode(), stored_hash.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(401, "invalid credentials", headers=_UNAUTH)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && python -m pytest tests/test_api_webhook.py -v`
Expected: PASS (all parsing + auth tests pass).

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/api/routers/webhook.py source_code/tests/test_api_webhook.py
git commit -m "feat(webhook): HTTP Basic auth verification against stored creds"
```

---

## Task 3: Background processor + coalescer

**Files:**
- Modify: `source_code/transcoder/api/routers/webhook.py`
- Test: `source_code/tests/test_api_webhook.py`

- [ ] **Step 1: Write the failing test**

Append to `source_code/tests/test_api_webhook.py`:

```python
def test_process_webhook_discovers_and_enqueues(monkeypatch):
    calls = {}
    monkeypatch.setattr(webhook, "build_clients", lambda: {"sonarr": "S", "radarr": "R"})

    class _FakeSession:
        def close(self): pass
    monkeypatch.setattr(webhook, "SessionLocal", lambda: _FakeSession())

    def fake_discover_sonarr(session, client, scope, target_title):
        calls["discover"] = ("sonarr", scope, target_title)
        return 1
    monkeypatch.setattr(webhook, "discover_sonarr", fake_discover_sonarr)
    monkeypatch.setattr(webhook, "discover_radarr", lambda *a, **k: 0)
    monkeypatch.setattr(webhook, "enqueue_eligible", lambda session, source: calls.setdefault("enqueue", source) or 2)
    monkeypatch.setattr(webhook.controller, "wake", lambda: calls.setdefault("woke", True))

    webhook._process_webhook("sonarr", "Breaking Bad")

    assert calls["discover"] == ("sonarr", "all", "Breaking Bad")
    assert calls["enqueue"] == "sonarr"
    assert calls["woke"] is True


def test_process_webhook_coalesces_pending(monkeypatch):
    monkeypatch.setattr(webhook, "build_clients", lambda: (_ for _ in ()).throw(AssertionError("should not run")))
    webhook._pending.add(("sonarr", "Breaking Bad"))
    try:
        # Returns early without touching build_clients.
        webhook._process_webhook("sonarr", "Breaking Bad")
    finally:
        webhook._pending.discard(("sonarr", "Breaking Bad"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && python -m pytest tests/test_api_webhook.py -k process_webhook -v`
Expected: FAIL — `AttributeError: ... has no attribute '_process_webhook'` / `_pending`.

- [ ] **Step 3: Write minimal implementation**

Add to `source_code/transcoder/api/routers/webhook.py` (imports near the top, code below the auth helpers):

```python
import threading

from transcoder.api.state import build_clients, controller
from transcoder.engine.discovery import discover_sonarr, discover_radarr
from transcoder.engine.queue import enqueue_eligible

_pending: set[tuple[str, str]] = set()
_pending_lock = threading.Lock()


def _process_webhook(source: str, title: str) -> None:
    """Targeted discover + enqueue for a single title, then wake the worker.

    A burst of webhooks for the same (source, title) is coalesced: while one is
    in flight, duplicates return immediately (the in-flight discover re-scans the
    whole series/movie anyway)."""
    key = (source, title)
    with _pending_lock:
        if key in _pending:
            log.info("Webhook coalesced: (%s) %s already pending", source, title)
            return
        _pending.add(key)
    try:
        clients = build_clients()
        session = SessionLocal()
        try:
            if source == "sonarr":
                discover_sonarr(session, clients["sonarr"], scope="all", target_title=title)
            else:
                discover_radarr(session, clients["radarr"], target_movie=title)
            created = enqueue_eligible(session, source=source)
        finally:
            session.close()
        controller.wake()
        log.info("Webhook processed: source=%s title=%s enqueued=%d", source, title, created)
    except Exception:  # noqa: BLE001
        log.exception("Webhook processing failed: source=%s title=%s", source, title)
    finally:
        with _pending_lock:
            _pending.discard(key)
```

Note: `enqueue_eligible` is called with the keyword `source=` to match its signature `enqueue_eligible(session, source=None)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && python -m pytest tests/test_api_webhook.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/api/routers/webhook.py source_code/tests/test_api_webhook.py
git commit -m "feat(webhook): targeted background processor with burst coalescing"
```

---

## Task 4: The endpoint + router registration

**Files:**
- Modify: `source_code/transcoder/api/routers/webhook.py`
- Modify: `source_code/transcoder/api/app.py:95-103` (router includes)
- Test: `source_code/tests/test_api_webhook.py`

- [ ] **Step 1: Write the failing test**

Append to `source_code/tests/test_api_webhook.py`:

```python
def _seed_db_creds(Session, user="hookuser", pw="hookpass"):
    from transcoder.repo import set_setting
    pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    s = Session()
    set_setting(s, "webhook_username", user)
    set_setting(s, "webhook_password_hash", pw_hash)
    s.commit()
    s.close()


def test_endpoint_accepts_import_and_schedules(api, monkeypatch):
    client, Session = api
    # Point the webhook module's DB + discovery at the test fixtures.
    monkeypatch.setattr(webhook, "SessionLocal", Session)
    _seed_db_creds(Session)
    scheduled = {}
    monkeypatch.setattr(webhook, "_process_webhook",
                        lambda source, title: scheduled.update(source=source, title=title))

    r = client.post(
        "/api/webhook/sonarr",
        headers={"Authorization": _basic("hookuser", "hookpass")},
        json={"eventType": "Download", "series": {"title": "Breaking Bad"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    # TestClient runs the BackgroundTask synchronously before returning.
    assert scheduled == {"source": "sonarr", "title": "Breaking Bad"}


def test_endpoint_rejects_bad_auth(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(webhook, "SessionLocal", Session)
    _seed_db_creds(Session)
    r = client.post(
        "/api/webhook/sonarr",
        headers={"Authorization": _basic("hookuser", "WRONG")},
        json={"eventType": "Download", "series": {"title": "X"}},
    )
    assert r.status_code == 401


def test_endpoint_unknown_source_404(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(webhook, "SessionLocal", Session)
    _seed_db_creds(Session)
    r = client.post(
        "/api/webhook/plex",
        headers={"Authorization": _basic("hookuser", "hookpass")},
        json={"eventType": "Download"},
    )
    assert r.status_code == 404


def test_endpoint_test_event_is_noop(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(webhook, "SessionLocal", Session)
    _seed_db_creds(Session)
    called = {"n": 0}
    monkeypatch.setattr(webhook, "_process_webhook", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    r = client.post(
        "/api/webhook/sonarr",
        headers={"Authorization": _basic("hookuser", "hookpass")},
        json={"eventType": "Test", "series": {"title": "Breaking Bad"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
    assert called["n"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && python -m pytest tests/test_api_webhook.py -k endpoint -v`
Expected: FAIL — `404` for all (route not registered yet), so assertions on `status`/`accepted` fail.

- [ ] **Step 3: Write minimal implementation**

Add the router + endpoint to `source_code/transcoder/api/routers/webhook.py` (router near the top after `log`, endpoint at the bottom):

```python
from fastapi import APIRouter, BackgroundTasks

router = APIRouter(prefix="/api")


@router.post("/webhook/{source}")
async def receive_webhook(source: str, request: Request, background: BackgroundTasks):
    verify_webhook_auth(request)
    if source not in ("sonarr", "radarr"):
        raise HTTPException(404, "unknown source")
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "invalid JSON body")

    if payload.get("eventType") != "Download":
        return {"status": "ignored", "event": payload.get("eventType")}

    title = extract_title(source, payload)
    if not title:
        log.warning("Webhook %s import event with no title in payload", source)
        return {"status": "ignored", "reason": "no title"}

    background.add_task(_process_webhook, source, title)
    return {"status": "accepted", "title": title}
```

Then register it **without** `require_auth` in `source_code/transcoder/api/app.py`. Change the open-routes section (currently around line 92):

```python
    # Open: health (defined above) + auth + webhook (self-authenticates via Basic).
    app.include_router(auth_router)
    from transcoder.api.routers import webhook
    app.include_router(webhook.router)
```

(Leave the protected-routers block below it unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && python -m pytest tests/test_api_webhook.py -v`
Expected: PASS (all webhook tests).

- [ ] **Step 5: Commit**

```bash
git add source_code/transcoder/api/routers/webhook.py source_code/transcoder/api/app.py source_code/tests/test_api_webhook.py
git commit -m "feat(webhook): POST /api/webhook/{source} endpoint, registered open"
```

---

## Task 5: Settings backend plumbing for webhook credentials

**Files:**
- Modify: `source_code/transcoder/api/schemas.py:133-166`
- Modify: `source_code/transcoder/api/routers/settings.py:28-103`
- Test: `source_code/tests/test_api_settings_webhook.py`

- [ ] **Step 1: Write the failing test**

Create `source_code/tests/test_api_settings_webhook.py`:

```python
import bcrypt


def test_settings_reports_webhook_password_set_false_by_default(api):
    client, _ = api
    data = client.get("/api/settings").json()
    assert data["webhook_username"] == ""
    assert data["webhook_password_set"] is False


def test_update_sets_webhook_username_and_password(api):
    client, Session = api
    r = client.put("/api/settings", json={
        "webhook_username": "hookuser",
        "webhook_password": "hookpass",
    })
    assert r.status_code == 200

    from transcoder.repo import get_setting
    s = Session()
    assert get_setting(s, "webhook_username") == "hookuser"
    stored_hash = get_setting(s, "webhook_password_hash")
    s.close()
    assert stored_hash and bcrypt.checkpw(b"hookpass", stored_hash.encode())

    data = client.get("/api/settings").json()
    assert data["webhook_username"] == "hookuser"
    assert data["webhook_password_set"] is True


def test_update_without_password_keeps_existing(api):
    client, Session = api
    client.put("/api/settings", json={"webhook_username": "u1", "webhook_password": "p1"})
    from transcoder.repo import get_setting
    s = Session()
    first_hash = get_setting(s, "webhook_password_hash")
    s.close()
    # Update only the username; omit the password.
    client.put("/api/settings", json={"webhook_username": "u2"})
    s = Session()
    assert get_setting(s, "webhook_username") == "u2"
    assert get_setting(s, "webhook_password_hash") == first_hash
    s.close()
```

Note: the `api` fixture monkeypatches `app_module.SessionLocal` and overrides `get_session` to the in-memory DB, so the settings router (which uses the `get_session` dependency) reads/writes the test DB.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code && python -m pytest tests/test_api_settings_webhook.py -v`
Expected: FAIL — `KeyError: 'webhook_username'` (field not in `SettingsOut`).

- [ ] **Step 3: Write minimal implementation**

In `source_code/transcoder/api/schemas.py`, add two fields to `SettingsOut` (after `scheduler_next_run`):

```python
    scheduler_next_run: str | None = None
    webhook_username: str = ""
    webhook_password_set: bool = False
```

And two to `SettingsUpdate` (after `new_password`):

```python
    current_password: str | None = None
    new_password: str | None = None
    webhook_username: str | None = None
    webhook_password: str | None = None
```

In `source_code/transcoder/api/routers/settings.py`:

Import bcrypt is already present. In `get_settings`, add the two fields to the returned `SettingsOut(...)`:

```python
        scheduler_next_run=state.scheduler.next_run(),
        webhook_username=get_effective(db, "webhook_username", ""),
        webhook_password_set=bool(get_setting(db, "webhook_password_hash")),
    )
```

In `update_settings`, add `"webhook_username"` to the `simple_fields` list:

```python
    simple_fields = [
        "sonarr_url", "radarr_url", "sftp_host", "sftp_port", "sftp_username",
        "handbrake_cli", "handbrake_preset_1080", "handbrake_preset_4k",
        "scheduler_run_at_startup", "webhook_username",
    ]
```

And handle the webhook password (hash on save) — add right after the password block, before `simple_fields` is processed or after it; place it after the credential loop:

```python
    if body.webhook_password is not None and body.webhook_password not in ("", _REDACTED):
        wh_hash = bcrypt.hashpw(body.webhook_password.encode(), bcrypt.gensalt()).decode()
        set_setting(db, "webhook_password_hash", wh_hash)
        updated.append("webhook_password")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd source_code && python -m pytest tests/test_api_settings_webhook.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `cd source_code && python -m pytest -q`
Expected: PASS (all green, including pre-existing tests).

- [ ] **Step 6: Commit**

```bash
git add source_code/transcoder/api/schemas.py source_code/transcoder/api/routers/settings.py source_code/tests/test_api_settings_webhook.py
git commit -m "feat(settings): store + expose webhook basic-auth credentials"
```

---

## Task 6: Frontend types + Settings "Webhooks" section

**Files:**
- Modify: `source_code/web/src/api/types.ts:36-69`
- Modify: `source_code/web/src/pages/Settings.tsx`
- Test: `source_code/web/src/pages/Settings.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `source_code/web/src/pages/Settings.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import Settings from "./Settings";

afterEach(() => vi.restoreAllMocks());

const SETTINGS = {
  scheduler_cron: null, scheduler_run_at_startup: "false",
  sonarr_url: "http://sonarr", sonarr_api_key: "", radarr_url: "http://radarr",
  radarr_api_key: "", sftp_host: "h", sftp_port: "22", sftp_username: "u",
  sftp_password: "", handbrake_cli: "hb", handbrake_preset_1080: "p1",
  handbrake_preset_4k: "p2", scheduler_next_run: null,
  webhook_username: "", webhook_password_set: false,
};

function makeFetch(captured: { body?: string }) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/settings") && (!init || init.method === "GET")) {
      return new Response(JSON.stringify(SETTINGS), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/api/settings") && init?.method === "PUT") {
      captured.body = init.body as string;
      return new Response(JSON.stringify({ updated: ["webhook_username"] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Settings /></MemoryRouter>
    </QueryClientProvider>,
  );
}

test("shows the webhook URLs", async () => {
  const captured: { body?: string } = {};
  vi.stubGlobal("fetch", makeFetch(captured));
  renderPage();
  expect(await screen.findByText(/\/api\/webhook\/sonarr/)).toBeInTheDocument();
  expect(screen.getByText(/\/api\/webhook\/radarr/)).toBeInTheDocument();
});

test("saving webhook section sends username", async () => {
  const captured: { body?: string } = {};
  vi.stubGlobal("fetch", makeFetch(captured));
  renderPage();
  const userInput = await screen.findByLabelText(/webhook username/i);
  fireEvent.change(userInput, { target: { value: "hookuser" } });
  fireEvent.click(screen.getByRole("button", { name: /save webhook settings/i }));
  await waitFor(() => expect(captured.body).toBeTruthy());
  expect(JSON.parse(captured.body!)).toMatchObject({ webhook_username: "hookuser" });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd source_code/web && npm test -- Settings`
Expected: FAIL — the webhook URLs / labelled input don't exist yet.

- [ ] **Step 3: Add the frontend types**

In `source_code/web/src/api/types.ts`, add to the `Settings` interface (after `scheduler_next_run`):

```ts
  scheduler_next_run: string | null;
  webhook_username: string;
  webhook_password_set: boolean;
}
```

And to `SettingsUpdate` (after `new_password`):

```ts
  current_password?: string;
  new_password?: string;
  webhook_username?: string;
  webhook_password?: string;
}
```

- [ ] **Step 4: Add the Webhooks section to Settings.tsx**

In `source_code/web/src/pages/Settings.tsx`:

Add state with the other section state (near the Security block, before the `useEffect` seed):

```tsx
  // Webhooks
  const [webhookUser, setWebhookUser] = useState('');
  const [webhookPass, setWebhookPass] = useState(REDACTED);
  const [webhookSaved, setWebhookSaved] = useState(false);
  const [webhookError, setWebhookError] = useState<string | null>(null);
  const [webhookDirty, setWebhookDirty] = useState(false);
```

Seed it inside the existing `useEffect(... [data])`, alongside the other seeds:

```tsx
    setWebhookUser(data.webhook_username || '');
    setWebhookPass(data.webhook_password_set ? REDACTED : '');
    setWebhookDirty(false);
```

Add a mutation with the others:

```tsx
  const webhookMut = useMutation({ mutationFn: updateSettings, onSuccess });
```

Add a derived base URL near `cronDescription`:

```tsx
  const webhookBase = `${window.location.origin}/api/webhook`;
```

Add the section JSX after the Security `</section>` and before the closing `</main>`:

```tsx
      {/* ── Webhooks ── */}
      <section aria-labelledby="webhook-heading" className="mb-6">
        <Card>
          <CardHeader className="flex flex-row items-center gap-2 border-b border-border">
            <h2 id="webhook-heading" className="font-display text-lg text-fg">Webhooks</h2>
            {webhookDirty && <DirtyDot />}
          </CardHeader>
          <CardContent className="space-y-4 pt-5">
            <p className="text-sm text-muted">
              Add a <span className="font-medium text-fg">Webhook</span> connection in Sonarr and
              Radarr (Settings → Connect) pointing at the URLs below, triggered <span className="font-medium text-fg">On Import</span> and
              <span className="font-medium text-fg"> On Import Upgrade</span>. Use the username and
              password below as the connection's Basic-auth credentials. The host must be reachable
              from the Sonarr/Radarr machine.
            </p>

            <div className="space-y-1 text-sm">
              <div className="text-xs font-medium text-muted">Sonarr URL</div>
              <code className="block break-all rounded bg-elevated px-2 py-1 font-mono text-xs text-fg">
                {webhookBase}/sonarr
              </code>
              <div className="pt-2 text-xs font-medium text-muted">Radarr URL</div>
              <code className="block break-all rounded bg-elevated px-2 py-1 font-mono text-xs text-fg">
                {webhookBase}/radarr
              </code>
            </div>

            <Field htmlFor="webhook-user" label="Webhook username">
              <Input id="webhook-user" value={webhookUser}
                onChange={e => { setWebhookUser(e.target.value); setWebhookDirty(true); }} />
            </Field>
            <Field htmlFor="webhook-pass" label="Webhook password">
              <MaskedInput id="webhook-pass" fieldLabel="Webhook password"
                value={webhookPass} onChange={v => { setWebhookPass(v); setWebhookDirty(true); }} />
            </Field>

            <div className="flex items-center gap-3 border-t border-border pt-4">
              <Button size="sm"
                onClick={() => save(
                  {
                    webhook_username: webhookUser,
                    ...(webhookPass !== REDACTED ? { webhook_password: webhookPass } : {}),
                  },
                  webhookMut.mutateAsync, setWebhookSaved, setWebhookError, setWebhookDirty,
                )}
                disabled={webhookMut.isPending}
                aria-busy={webhookMut.isPending}
                aria-label="Save Webhook settings">
                {webhookMut.isPending ? 'Saving…' : 'Save'}
              </Button>
              <StatusMessage saving={webhookMut.isPending} saved={webhookSaved} error={webhookError} />
            </div>
          </CardContent>
        </Card>
      </section>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd source_code/web && npm test -- Settings`
Expected: PASS (both tests).

- [ ] **Step 6: Type-check / build the frontend**

Run: `cd source_code/web && npm run build`
Expected: build succeeds (no TS errors).

- [ ] **Step 7: Commit**

```bash
git add source_code/web/src/api/types.ts source_code/web/src/pages/Settings.tsx source_code/web/src/pages/Settings.test.tsx
git commit -m "feat(web): Webhooks settings section with copy-able URLs + Basic-auth creds"
```

---

## Task 7: Document the endpoint

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the endpoint list**

In `CLAUDE.md`, in the "Serve (API, Cycle 2)" key-endpoints paragraph, add the webhook endpoint to the list:

```
`POST /api/library/{id}/enqueue`, `POST /api/webhook/{source}` (open; HTTP Basic
auth; Sonarr/Radarr call it on import to trigger a targeted discover + enqueue).
```

And in the Web UI screens line, note the Settings page now configures webhooks:

```
Settings (connections, scheduler, encoder, security, and Sonarr/Radarr webhook credentials).
```

(If that exact Settings sentence isn't present, add a short note in the Web UI section that the Settings page configures the webhook Basic-auth credentials and shows the two webhook URLs.)

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the Sonarr/Radarr webhook endpoint"
```

---

## Final verification

- [ ] **Run the whole backend suite:** `cd source_code && python -m pytest -q` — all green.
- [ ] **Run the whole frontend suite:** `cd source_code/web && npm test` — all green.
- [ ] **Build the frontend:** `cd source_code/web && npm run build` — succeeds.
- [ ] **Manual smoke (optional):** start the API (`cd source_code && python -m transcoder.api`), set webhook creds on the Settings page, then `curl -u hookuser:hookpass -H "Content-Type: application/json" -d '{"eventType":"Download","series":{"title":"Some Show"}}' http://localhost:8765/api/webhook/sonarr` and confirm a `{"status":"accepted"}` response and a discover/enqueue line on the Logs page.

---

## Spec self-review notes

- **Spec coverage:** webhook router (Tasks 1–4), Basic auth (Task 2), targeted discover + enqueue + coalescer (Task 3), open registration (Task 4), settings storage + UI surface (Tasks 5–6), the two URLs in the UI (Task 6), docs (Task 7). All spec sections map to a task.
- **Loop prevention / feedback-loop:** no code needed — it falls out of the existing eligibility rule (re-imported H.265 file is not eligible). Documented in the spec; nothing to implement.
- **Concurrency:** the processor opens its own session and does not take the `scan_status` lock, matching the spec's "independent, lightweight" decision.
- **Type consistency:** `_load_creds()`, `verify_webhook_auth()`, `_process_webhook()`, `extract_title()`, `_pending`, `receive_webhook` names are used consistently across tasks; `enqueue_eligible(session, source=…)` matches `queue.py`; `SettingsOut.webhook_password_set` / `SettingsUpdate.webhook_password` names match between backend and frontend.
