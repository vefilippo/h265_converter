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
    client.put("/api/settings", json={"webhook_username": "u2"})
    s = Session()
    assert get_setting(s, "webhook_username") == "u2"
    assert get_setting(s, "webhook_password_hash") == first_hash
    s.close()
