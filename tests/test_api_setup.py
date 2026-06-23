"""First-run setup: an empty install reports needs_setup and can set the initial
password via an open endpoint that becomes inert once a password exists."""
import transcoder.api.auth as auth
from transcoder.models import Setting


def _make_empty(api, monkeypatch):
    """Put the in-memory DB into the 'no password configured' state."""
    client, Session = api
    monkeypatch.setattr(auth.settings, "APP_PASSWORD", "")
    with Session() as db:
        db.query(Setting).filter(Setting.key == "app_password_hash").delete()
        db.commit()
    return client, Session


def test_me_reports_needs_setup_when_no_password(api, monkeypatch):
    client, _ = _make_empty(api, monkeypatch)
    body = client.get("/api/me").json()
    assert body["needs_setup"] is True


def test_me_no_setup_when_password_hash_exists(api):
    # Default fixture seeds app_password_hash (APP_PASSWORD="test-pass").
    client, _ = api
    assert client.get("/api/me").json()["needs_setup"] is False


def test_setup_password_sets_hash_and_authes(api, monkeypatch):
    client, Session = _make_empty(api, monkeypatch)
    r = client.post("/api/setup/password", json={"password": "hunter2"})
    assert r.status_code == 200 and r.json()["ok"] is True
    # Session is now authed and setup is complete.
    me = client.get("/api/me").json()
    assert me["authed"] is True and me["needs_setup"] is False
    # Hash persisted.
    with Session() as db:
        assert db.get(Setting, "app_password_hash") is not None


def test_setup_password_conflicts_when_already_configured(api):
    client, _ = api  # default fixture already has a password hash
    r = client.post("/api/setup/password", json={"password": "whatever"})
    assert r.status_code == 409


def test_setup_password_rejects_blank(api, monkeypatch):
    client, _ = _make_empty(api, monkeypatch)
    r = client.post("/api/setup/password", json={"password": "   "})
    assert r.status_code == 422


def test_setup_password_conflicts_when_only_env_password_set(api, monkeypatch):
    """An install configured purely via env APP_PASSWORD (no DB hash) is already
    configured — the open endpoint must stay inert (409) for it too, not just
    when a hash exists."""
    client, Session = api
    monkeypatch.setattr(auth.settings, "APP_PASSWORD", "env-pass")
    with Session() as db:
        db.query(Setting).filter(Setting.key == "app_password_hash").delete()
        db.commit()
    assert client.get("/api/me").json()["needs_setup"] is False
    r = client.post("/api/setup/password", json={"password": "whatever"})
    assert r.status_code == 409
