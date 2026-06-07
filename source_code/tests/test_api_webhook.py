from transcoder.api.routers.webhook import extract_title


def test_extract_title_sonarr():
    payload = {"eventType": "Download", "series": {"title": "Breaking Bad"}}
    assert extract_title("sonarr", payload) == "Breaking Bad"


def test_extract_title_radarr():
    payload = {"eventType": "Download", "movie": {"title": "Inception", "year": 2010}}
    assert extract_title("radarr", payload) == "Inception"


def test_extract_title_missing_returns_none():
    assert extract_title("sonarr", {"eventType": "Test"}) is None
    assert extract_title("radarr", {"movie": {}}) is None
    assert extract_title("sonarr", {"series": None}) is None
