import transcoder.api.app as app_module


def test_apply_pending_restore_called_before_init_db(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "apply_pending_restore",
                        lambda *a, **k: calls.append("restore") or False)
    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: calls.append("init_db"))
    monkeypatch.setattr(app_module, "backup_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "ensure_job_columns", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)

    app = app_module.create_app(start_worker=False)
    from fastapi.testclient import TestClient
    with TestClient(app):
        pass
    assert calls[:2] == ["restore", "init_db"]


def test_backup_router_registered():
    app = app_module.create_app(start_worker=False)
    paths = set(app.openapi()["paths"].keys())
    assert "/api/backup" in paths and "/api/restore" in paths
