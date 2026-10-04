import pytest

from transcoder.arr_import import ImportNotQueued, pick_candidate, release_quality


def _q(name="Bluray-1080p", **revision):
    q = {"quality": {"name": name, "resolution": 1080}}
    if revision:
        q["revision"] = revision
    return q


@pytest.mark.parametrize("revision, expected", [
    ({"version": 1, "real": 0, "isRepack": False}, "Bluray-1080p"),
    ({"version": 2, "real": 0, "isRepack": False}, "Bluray-1080p Proper"),
    ({"version": 2, "real": 0, "isRepack": True}, "Bluray-1080p REPACK"),
    ({"version": 3, "real": 0, "isRepack": False}, "Bluray-1080p REPACK2"),
    ({"version": 4, "real": 0, "isRepack": True}, "Bluray-1080p REPACK3"),
    ({"version": 1, "real": 1, "isRepack": False}, "Bluray-1080p REAL"),
    ({"version": 2, "real": 1, "isRepack": False}, "Bluray-1080p REAL Proper"),
])
def test_release_quality_renders_revision_tokens(revision, expected):
    assert release_quality(_q(**revision)) == expected


def test_release_quality_without_revision_is_plain_name():
    assert release_quality(_q()) == "Bluray-1080p"
    assert release_quality({"quality": {"name": "HDTV-720p"}, "revision": None}) == "HDTV-720p"


def test_release_quality_missing_quality_is_unknown():
    assert release_quality(None) == "Unknown Quality"
    assert release_quality({}) == "Unknown Quality"


def test_pick_candidate_returns_unrejected_match_ignoring_case_and_slashes():
    good = {"path": "/downloads/Movie (2025).mkv", "rejections": []}
    other = {"path": "/downloads/Other.mkv", "rejections": []}
    assert pick_candidate([other, good], "/Downloads/movie (2025).mkv", "Radarr") is good


def test_pick_candidate_raises_with_all_rejection_reasons():
    rejected = {"path": "/downloads/M.mkv", "rejections": [
        {"reason": "Not an upgrade for existing movie file(s)", "type": "permanent"},
        {"reason": "Sample", "type": "permanent"},
    ]}
    with pytest.raises(ImportNotQueued) as exc:
        pick_candidate([rejected], "/downloads/M.mkv", "Radarr")
    msg = str(exc.value)
    assert msg.startswith("Radarr rejected /downloads/M.mkv: ")
    assert "Not an upgrade for existing movie file(s); Sample" in msg


def test_pick_candidate_raises_when_path_not_listed():
    with pytest.raises(ImportNotQueued, match="Sonarr did not find /downloads/E.mkv"):
        pick_candidate([{"path": "/downloads/X.mkv", "rejections": []}], "/downloads/E.mkv", "Sonarr")


def test_import_not_queued_is_a_runtime_error():
    assert issubclass(ImportNotQueued, RuntimeError)
