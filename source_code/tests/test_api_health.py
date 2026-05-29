from fastapi.testclient import TestClient

from transcoder.api.app import create_app


def test_health_ok():
    app = create_app(start_worker=False)
    with TestClient(app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
