from transcoder.radarr_client import RadarrClient
from transcoder.sonarr_client import SonarrClient


def test_sonarr_extract_quality_keeps_proper():
    ef = {"quality": {"quality": {"name": "WEBDL-1080p", "resolution": 1080},
                      "revision": {"version": 2, "real": 0, "isRepack": False}}}
    assert SonarrClient.extract_quality(ef) == "WEBDL-1080p Proper"


def test_sonarr_extract_quality_without_quality_is_unknown():
    assert SonarrClient.extract_quality({}) == "Unknown Quality"


def _movie(quality):
    return {"id": 696, "title": "The Long Walk", "year": 2025, "movieFile": {
        "id": 2749, "path": "/movies/x.mkv", "mediaInfo": {"videoCodec": "x264"},
        "languages": [{"name": "Italian"}], "quality": quality,
    }}


def test_radarr_quality_keeps_proper():
    q = {"quality": {"name": "Bluray-1080p", "resolution": 1080},
         "revision": {"version": 2, "real": 0, "isRepack": False}}
    rows = RadarrClient("http://r", "k").filter_non_h265_movies([_movie(q)])
    assert rows[0]["quality"] == "Bluray-1080p Proper"
    assert rows[0]["resolution"] == 1080


def test_radarr_missing_quality_does_not_crash_scan():
    rows = RadarrClient("http://r", "k").filter_non_h265_movies([_movie(None)])
    assert rows[0]["quality"] == "Unknown Quality"
    assert rows[0]["resolution"] is None
