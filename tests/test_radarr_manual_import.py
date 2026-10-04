import pytest
import requests

from transcoder import radarr_client
from transcoder.arr_import import ImportNotQueued
from transcoder.radarr_client import RadarrClient

PATH = "/downloads/M (2025) [h265] Bluray-1080p Proper Release-OPO.mkv"


class _Resp:
    def __init__(self, payload=None, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


@pytest.fixture
def http(monkeypatch):
    calls = {"post": []}
    monkeypatch.setattr(radarr_client.settings, "DOCKER_HOST_ROOT", "./out/")
    monkeypatch.setattr(radarr_client.settings, "DOCKER_DOCKER_ROOT", "/downloads/")

    def install(get_payload, get_status=200, post_status=201):
        monkeypatch.setattr(radarr_client.requests, "get",
                            lambda *a, **k: _Resp(get_payload, get_status))

        def post(url, **kw):
            calls["post"].append(kw["json"])
            return _Resp({}, post_status)
        monkeypatch.setattr(radarr_client.requests, "post", post)
        return calls
    return install


def _cand(rejections=()):
    return {"path": PATH, "movie": {"id": 696}, "quality": {"q": 1},
            "languages": [], "releaseGroup": "OPO", "indexerFlags": 0,
            "rejections": list(rejections)}


def test_queues_import_for_accepted_candidate(http):
    calls = http([_cand()])
    RadarrClient("http://r", "k").manual_import_one("./out/" + PATH.split("/")[-1])
    assert calls["post"][0]["name"] == "ManualImport"
    assert calls["post"][0]["files"][0]["movieId"] == 696


def test_rejected_candidate_raises_with_reason(http):
    calls = http([_cand([{"reason": "Not an upgrade for existing movie file(s)"}])])
    with pytest.raises(ImportNotQueued, match="Radarr rejected .*Not an upgrade"):
        RadarrClient("http://r", "k").manual_import_one("./out/" + PATH.split("/")[-1])
    assert calls["post"] == []


def test_missing_candidate_raises(http):
    http([])
    with pytest.raises(ImportNotQueued, match="Radarr did not find"):
        RadarrClient("http://r", "k").manual_import_one("./out/" + PATH.split("/")[-1])


def test_http_error_raises_import_not_queued(http):
    http([_cand()], post_status=500)
    with pytest.raises(ImportNotQueued, match="Radarr manual import failed"):
        RadarrClient("http://r", "k").manual_import_one("./out/" + PATH.split("/")[-1])
