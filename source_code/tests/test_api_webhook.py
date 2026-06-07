import base64

import bcrypt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import transcoder.api.routers.webhook as webhook
from transcoder.api.routers.webhook import extract_title

# Computed once at module load; shared by all _seed_creds callers.
_HOOKPASS = "hookpass"
_HOOKPASS_HASH = bcrypt.hashpw(_HOOKPASS.encode(), bcrypt.gensalt()).decode()


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
    # Use the pre-computed hash when pw matches the default; re-hash only for overrides.
    pw_hash = _HOOKPASS_HASH if pw == _HOOKPASS else bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    store = {"webhook_username": user, "webhook_password_hash": pw_hash}
    monkeypatch.setattr(webhook, "_load_creds", lambda: (store["webhook_username"], store["webhook_password_hash"]))


def test_verify_auth_accepts_valid(monkeypatch):
    _seed_creds(monkeypatch)
    webhook.verify_webhook_auth(_make_request(_basic("hookuser", "hookpass")))


def test_verify_auth_rejects_wrong_password(monkeypatch):
    _seed_creds(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        webhook.verify_webhook_auth(_make_request(_basic("hookuser", "WRONG")))
    assert exc.value.status_code == 401
    assert exc.value.headers.get("WWW-Authenticate") == "Basic"


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
    assert exc.value.headers.get("WWW-Authenticate") == "Basic"


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
    monkeypatch.setattr(webhook, "discover_radarr", lambda *a, **k: calls.setdefault("radarr_called", True))
    monkeypatch.setattr(webhook, "enqueue_eligible", lambda session, source: calls.setdefault("enqueue", source) or 2)
    monkeypatch.setattr(webhook.controller, "wake", lambda: calls.setdefault("woke", True))

    webhook._process_webhook("sonarr", "Breaking Bad")

    assert calls["discover"] == ("sonarr", "all", "Breaking Bad")
    assert calls["enqueue"] == "sonarr"
    assert calls["woke"] is True
    assert "radarr_called" not in calls


def test_process_webhook_coalesces_pending(monkeypatch):
    monkeypatch.setattr(webhook, "build_clients", lambda: (_ for _ in ()).throw(AssertionError("should not run")))
    monkeypatch.setattr(webhook, "SessionLocal", lambda: (_ for _ in ()).throw(AssertionError("should not run")))
    seen = {}
    webhook._pending.add(("sonarr", "Breaking Bad"))
    try:
        # build_clients/SessionLocal raise if reached → reaching here proves the early return
        webhook._process_webhook("sonarr", "Breaking Bad")
    finally:
        webhook._pending.discard(("sonarr", "Breaking Bad"))
