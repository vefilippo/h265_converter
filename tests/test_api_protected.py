def test_routers_protected_without_session(api):
    client, Session = api
    client.post("/api/logout")
    # one endpoint from every protected router
    assert client.get("/api/library").status_code == 401
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/status").status_code == 401          # stream router
    assert client.get("/api/exclusions").status_code == 401
    assert client.get("/api/scan/status").status_code == 401
    assert client.post("/api/scan", json={"app": "all", "scope": "all"}).status_code == 401
    # open routes stay reachable
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/me").json()["authed"] is False


def test_reauth_restores_access(api):
    client, Session = api
    client.post("/api/logout")
    assert client.get("/api/library").status_code == 401
    client.post("/api/login", json={"password": "test-pass"})
    assert client.get("/api/library").status_code == 200
