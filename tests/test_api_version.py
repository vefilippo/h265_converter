def test_version_endpoint_returns_version(api):
    client, _ = api
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json() == {"version": "1.0.0"}


def test_version_endpoint_is_open(api):
    client, _ = api
    client.cookies.clear()  # drop the fixture's session cookie
    r = client.get("/api/version")
    assert r.status_code == 200
