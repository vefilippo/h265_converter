"""SECRET_KEY signs session cookies and cannot be empty. On an empty install it
must be generated once and reused across restarts, persisted to a file beside
the database (the SessionMiddleware is added before init_db runs, so the DB is
not available yet)."""


def test_prefers_env_secret_when_set(monkeypatch):
    from transcoder import config
    monkeypatch.setattr(config.settings, "SECRET_KEY", "env-secret-value")
    assert config.resolve_secret_key() == "env-secret-value"


def test_generates_and_reuses_file_when_env_empty(monkeypatch, tmp_path):
    from transcoder import config
    monkeypatch.setattr(config.settings, "SECRET_KEY", "")
    db = tmp_path / "transcoder.db"
    monkeypatch.setattr(config.settings, "DATABASE_URL", f"sqlite:///{db.as_posix()}")

    first = config.resolve_secret_key()
    assert first  # non-empty
    assert (tmp_path / "secret_key").exists()

    second = config.resolve_secret_key()
    assert second == first  # reused, not regenerated
