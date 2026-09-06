import io
import sqlite3
import zipfile
from transcoder import backup


def test_backup_requires_auth(api):
    client, _ = api
    client.cookies.clear()  # drop the fixture's session cookie
    r = client.post("/api/backup", json={"passphrase": "x"})
    assert r.status_code == 401


def test_backup_returns_zip(api, tmp_path, monkeypatch):
    client, _ = api
    # Point the app's DB + env at temp files with known content.
    import transcoder.config as cfg
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    sqlite3.connect(str(db)).close()
    env.write_text("APP_PASSWORD=z\n", encoding="utf-8")
    monkeypatch.setattr(cfg.settings, "DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setattr("transcoder.api.routers.backup.ENV_PATH", str(env))

    r = client.post("/api/backup", json={"passphrase": "pw"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert set(names) == {"transcoder.db", "env.enc", "manifest.json"}


def test_restore_stages_and_returns_202(api, tmp_path, monkeypatch):
    client, _ = api
    shutdown = []
    client.app.state.request_shutdown = lambda: shutdown.append(True)
    src = tmp_path / "src.db"; sqlite3.connect(str(src)).close()
    (tmp_path / "src.env").write_text("X=1\n", encoding="utf-8")
    blob = backup.make_backup(str(src), str(tmp_path / "src.env"), "pw", created_at="now")

    staged = {}
    monkeypatch.setattr("transcoder.api.routers.backup.stage_restore",
                        lambda db, env, base: staged.update(db=db, env=env))
    monkeypatch.setattr("transcoder.api.routers.backup.schedule_relaunch", lambda *a, **k: None)

    r = client.post("/api/restore", files={"file": ("b.zip", blob, "application/zip")},
                    data={"passphrase": "pw"})
    assert r.status_code == 202 and r.json()["status"] == "restarting"
    assert staged["env"] == "X=1\n"
    assert shutdown == [True]
    assert client.get("/api/health").status_code == 503


def test_restore_rejected_without_restart_support(api, tmp_path, monkeypatch):
    client, _ = api
    src = tmp_path / "src.db"
    sqlite3.connect(src).close()
    blob = backup.make_backup(str(src), str(tmp_path / "missing.env"), "pw")
    staged = []
    monkeypatch.setattr("transcoder.api.routers.backup.stage_restore",
                        lambda *a: staged.append(True))
    monkeypatch.setattr("transcoder.api.routers.backup.schedule_relaunch", lambda **k: None)
    response = client.post("/api/restore", files={"file": ("b.zip", blob)},
                           data={"passphrase": "pw"})
    assert response.status_code == 503
    assert not staged


def test_restore_wrong_passphrase_400(api, tmp_path, monkeypatch):
    client, _ = api
    src = tmp_path / "s.db"; sqlite3.connect(str(src)).close()
    (tmp_path / "s.env").write_text("X=1\n", encoding="utf-8")
    blob = backup.make_backup(str(src), str(tmp_path / "s.env"), "right", created_at="now")
    monkeypatch.setattr("transcoder.api.routers.backup.schedule_relaunch", lambda *a, **k: None)
    r = client.post("/api/restore", files={"file": ("b.zip", blob, "application/zip")},
                    data={"passphrase": "wrong"})
    assert r.status_code == 400


def test_backup_manifest_carries_real_version(api, tmp_path, monkeypatch):
    import json
    import transcoder.config as cfg
    import transcoder.api.routers.backup as backup_router
    import transcoder.version as version_mod

    client, _ = api
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    sqlite3.connect(str(db)).close()
    env.write_text("X=1\n", encoding="utf-8")
    monkeypatch.setattr(cfg.settings, "DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setattr(backup_router, "ENV_PATH", str(env))
    monkeypatch.setattr(version_mod, "_VERSION_PATH", tmp_path / "VERSION")
    (tmp_path / "VERSION").write_text("9.9.9\n", encoding="utf-8")

    r = client.post("/api/backup", json={"passphrase": "pw"})
    assert r.status_code == 200
    manifest = json.loads(
        zipfile.ZipFile(io.BytesIO(r.content)).read("manifest.json")
    )
    assert manifest["app_version"] == "9.9.9"
