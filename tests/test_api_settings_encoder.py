from transcoder.repo import get_setting


def test_settings_exposes_encoder_family_and_fallback(api):
    client, _Session = api
    body = client.get("/api/settings").json()
    assert body["encoder_family"] == "auto"
    assert body["encoder_fallback_cpu"] == "true"


def test_settings_update_persists_encoder_family(api):
    client, Session = api
    r = client.put("/api/settings", json={"encoder_family": "vcn"})
    assert r.status_code == 200
    assert "encoder_family" in r.json()["updated"]
    with Session() as db:
        assert get_setting(db, "encoder_family") == "vcn"


def test_settings_update_can_disable_cpu_fallback(api):
    client, Session = api
    client.put("/api/settings", json={"encoder_fallback_cpu": "false"})
    with Session() as db:
        assert get_setting(db, "encoder_fallback_cpu") == "false"
    assert client.get("/api/settings").json()["encoder_fallback_cpu"] == "false"


def test_custom_family_keeps_free_text_presets_editable(api):
    client, Session = api
    client.put("/api/settings", json={
        "encoder_family": "custom",
        "handbrake_preset_1080": "Mine 1080",
        "handbrake_preset_4k": "Mine 4K",
    })
    body = client.get("/api/settings").json()
    assert body["encoder_family"] == "custom"
    assert body["handbrake_preset_1080"] == "Mine 1080"
