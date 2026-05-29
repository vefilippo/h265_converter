import logging


def test_logs_endpoint_returns_recent(api):
    client, Session = api
    logging.getLogger("transcoder").info("hello-from-test-12345")
    r = client.get("/api/logs")
    assert r.status_code == 200
    body = r.json()
    assert any("hello-from-test-12345" in ln["message"] for ln in body["lines"])
    assert body["last_seq"] >= 1


def test_logs_after_cursor(api):
    client, Session = api
    first = client.get("/api/logs").json()["last_seq"]
    logging.getLogger("transcoder").info("second-line-after-cursor")
    body = client.get("/api/logs", params={"after": first}).json()
    assert all(ln["seq"] > first for ln in body["lines"])
    assert any("second-line-after-cursor" in ln["message"] for ln in body["lines"])


def test_logs_protected(api):
    client, Session = api
    client.post("/api/logout")
    assert client.get("/api/logs").status_code == 401
