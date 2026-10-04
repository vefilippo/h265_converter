import pytest
import requests

from transcoder import sonarr_client
from transcoder.arr_import import ImportNotQueued
from transcoder.sonarr_client import SonarrClient

NAME = "Slow Horses - S06E02 - h265 - [ENGLISH] WEBDL-1080p Proper Release-OPO.mkv"
PATH = "/downloads/" + NAME


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
    monkeypatch.setattr(sonarr_client.settings, "DOCKER_HOST_ROOT", "./out/")
    monkeypatch.setattr(sonarr_client.settings, "DOCKER_DOCKER_ROOT", "/downloads/")

    def install(get_payload, get_status=200, post_status=201):
        monkeypatch.setattr(sonarr_client.requests, "get",
                            lambda *a, **k: _Resp(get_payload, get_status))

        def post(url, **kw):
            calls["post"].append(kw["json"])
            return _Resp({}, post_status)
        monkeypatch.setattr(sonarr_client.requests, "post", post)
        return calls
    return install


def _cand(rejections=()):
    return {"path": PATH, "series": {"id": 7}, "episodes": [{"id": 70}, {"id": 71}],
            "quality": {"q": 1}, "languages": [], "releaseGroup": "OPO",
            "indexerFlags": 0, "rejections": list(rejections)}


def test_queues_import_for_accepted_candidate(http):
    calls = http([_cand()])
    SonarrClient("http://s", "k").manual_import_one("./out/" + NAME)
    files = calls["post"][0]["files"][0]
    assert files["seriesId"] == 7 and files["episodeIds"] == [70, 71]


def test_rejected_candidate_raises_with_reason(http):
    calls = http([_cand([{"reason": "Not an upgrade for existing episode file(s)"}])])
    with pytest.raises(ImportNotQueued, match="Sonarr rejected .*Not an upgrade"):
        SonarrClient("http://s", "k").manual_import_one("./out/" + NAME)
    assert calls["post"] == []


def test_missing_candidate_raises(http):
    http([])
    with pytest.raises(ImportNotQueued, match="Sonarr did not find"):
        SonarrClient("http://s", "k").manual_import_one("./out/" + NAME)


def test_http_error_raises_import_not_queued(http):
    http([_cand()], get_status=503)
    with pytest.raises(ImportNotQueued, match="Sonarr manual import failed"):
        SonarrClient("http://s", "k").manual_import_one("./out/" + NAME)
