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
