from transcoder.engine import discovery
from transcoder.models import MediaItem, Exclusion


class FakeSonarr:
    def get_all_series(self):
        return [{"id": 1, "title": "Show A"}]

    def get_episodes(self, series_id):
        return [
            {"hasFile": True, "episodeFileId": 100, "seasonNumber": 1, "episodeNumber": 1},
            {"hasFile": True, "episodeFileId": 101, "seasonNumber": 1, "episodeNumber": 2},
            {"hasFile": False, "episodeFileId": 0, "seasonNumber": 1, "episodeNumber": 3},
        ]

    def get_episode_file(self, fid):
        files = {
            100: {"path": "/TVShows/a1.mkv", "size": 999},
            101: {"path": "/TVShows/a2.mkv", "size": 999},
        }
        return files[fid]

    def extract_resolution(self, ef):
        return 1080 if ef["path"].endswith("a1.mkv") else 720

    def is_h265_encoded(self, ef):
        return False

    def extract_quality(self, ef):
        return "HDTV-1080p"

    def extract_languages(self, ef):
        return "ENG"


def test_discover_sonarr_populates_items_with_eligibility(session):
    count = discovery.discover_sonarr(session, FakeSonarr(), scope="all")
    assert count == 2
    items = {i.external_id: i for i in session.query(MediaItem).all()}
    assert items["100"].eligibility == "needs_transcode"
    assert items["101"].eligibility == "below_1080p"
    assert items["100"].title == "Show A"
    assert items["100"].season == 1 and items["100"].episode == 1


def test_discover_sonarr_marks_excluded(session):
    session.add(Exclusion(source="sonarr", key="Show A|1|1", reason="output_larger"))
    session.commit()
    discovery.discover_sonarr(session, FakeSonarr(), scope="all")
    item = session.query(MediaItem).filter_by(external_id="100").one()
    assert item.eligibility == "excluded"


class FakeRadarr:
    def get_all_movies(self):
        return ["raw"]

    def filter_non_h265_movies(self, movies):
        return [{
            "title": "Movie X", "codec": "h264", "path": "/movies/x.mkv",
            "resolution": 2160, "quality": "Bluray-2160p", "languages": "ENG",
            "year": 2020, "movie_id": 55, "external_id": "555",
        }]


def test_discover_radarr_populates_items(session):
    count = discovery.discover_radarr(session, FakeRadarr())
    assert count == 1
    item = session.query(MediaItem).filter_by(source="radarr").one()
    assert item.external_id == "555"
    assert item.eligibility == "needs_transcode"
    assert item.year == 2020
    assert item.parent_id == 55
