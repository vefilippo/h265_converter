from transcoder import encoders
from transcoder.encoders import CPU
from transcoder.repo import get_setting, set_setting


def test_encoders_requires_auth(api):
    client, _Session = api
    client.post("/api/logout")
    assert client.get("/api/encoders").status_code in (401, 403)
    # /detect is the only route on this feature that shells out to a subprocess
    # with a caller-supplied path, so its auth is asserted explicitly: today it
    # is covered by the router-level dependency, but a later move to per-route
    # Depends (as routers/settings.py does) could drop it silently.
    assert client.post("/api/encoders/detect", json={}).status_code in (401, 403)


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
    monkeypatch.setattr(encoders, "probe", lambda cli, **kw: ({"vcn", CPU}, {"nvenc"}))
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
        return {"qsv", CPU}, {"vcn"}

    monkeypatch.setattr(encoders, "probe", fake_probe)
    client.post("/api/encoders/detect", json={"handbrake_cli": "D:/typed.exe"})
    assert seen["cli"] == "D:/typed.exe"


def test_detect_reports_failure_without_caching(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(encoders, "probe", lambda cli, **kw: (set(), set()))
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
    monkeypatch.setattr(encoders, "probe", lambda cli, **kw: ({"vcn", CPU}, set()))
    body = client.post("/api/encoders/detect", json={}).json()
    assert body["ok"] is False
    assert "not set" in body["error"].lower()


def test_encoders_response_shape_and_order(api):
    client, _ = api
    r = client.get("/api/encoders")
    assert r.status_code == 200
    body = r.json()
    assert [f["id"] for f in body["families"]] == ["vcn", "nvenc", "qsv", "cpu"]
    assert set(body) == {"available", "detected_at", "families"}
    for f in body["families"]:
        assert set(f) == {"id", "label", "preset_1080", "preset_4k", "hardware", "available"}


def test_whitespace_only_cli_path_reports_not_set(api):
    """A whitespace path is truthy, so it used to be probed -- the user saw
    'Could not run    .' instead of the friendly not-set message."""
    client, _ = api
    r = client.post("/api/encoders/detect", json={"handbrake_cli": "   "})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "HandBrake CLI path is not set"


def test_encoders_routes_declare_response_models():
    """The shape is a hard contract for committed frontend code; without a
    response_model it is absent from OpenAPI and unchecked by pydantic."""
    from transcoder.api.app import create_app

    schema = create_app(start_worker=False).openapi()
    get_op = schema["paths"]["/api/encoders"]["get"]
    assert "application/json" in get_op["responses"]["200"]["content"]
    assert "$ref" in str(get_op["responses"]["200"]["content"]["application/json"]["schema"])
