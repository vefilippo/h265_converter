"""Reaping orphaned media_item rows.

Sonarr mints a NEW episodeFileId every time the file behind an episode changes
(a quality upgrade it grabbed itself, or our own transcode being re-imported).
`media_item` is keyed on (source, external_id) == episodeFileId, so the old row
is orphaned: discovery never visits that id again, so it is never refreshed and
never removed. Those orphans are what duplicate the Library, and an orphan left
at `needs_transcode` is re-enqueued on every run and fails forever.

`reap_orphans` finds series that have more than one row for the same
(season, episode), asks Sonarr which episodeFileIds are live for those series,
and retires every row of theirs that is not.
"""

from transcoder.engine.reap import reap_orphans
from transcoder.engine.queue import enqueue_eligible
from transcoder.models import MediaItem


class FakeSonarr:
    """Records which series were queried so tests can assert the reap is
    targeted rather than a full-library walk."""

    def __init__(self, episodes_by_series):
        self._episodes = episodes_by_series
        self.queried = []

    def get_episodes(self, series_id):
        self.queried.append(series_id)
        return self._episodes[series_id]


def _ep(season, episode, file_id):
    """A Sonarr episode payload. file_id=None means hasFile is false."""
    return {
        "seasonNumber": season,
        "episodeNumber": episode,
        "hasFile": file_id is not None,
        "episodeFileId": file_id or 0,
    }


def _row(session, external_id, *, parent_id=1, season=1, episode=1,
         eligibility="already_h265", source="sonarr", title="Show A"):
    item = MediaItem(
        source=source, external_id=str(external_id), parent_id=parent_id,
        title=title, season=season, episode=episode,
        remote_path=f"/TVShows/{external_id}.mkv", resolution=1080,
        eligibility=eligibility,
    )
    session.add(item)
    session.commit()
    return item


def _eligibility(session, external_id):
    return (
        session.query(MediaItem)
        .filter_by(external_id=str(external_id))
        .one()
        .eligibility
    )


def test_retires_the_replaced_row_and_keeps_the_live_one(session):
    # S01E01 was upgraded: file 100 replaced by 101. Both rows are in the DB.
    _row(session, 100)
    _row(session, 101)
    client = FakeSonarr({1: [_ep(1, 1, 101)]})

    assert reap_orphans(session, client) == 1
    assert _eligibility(session, 100) == "superseded"
    assert _eligibility(session, 101) == "already_h265"


def test_retires_every_row_when_none_of_them_is_the_live_file(session):
    # The Ark S03E05: upgraded twice, so BOTH stored rows are dead and the live
    # file (102) has no row at all. "Keep the newest row" would keep a phantom.
    _row(session, 100)
    _row(session, 101)
    client = FakeSonarr({1: [_ep(1, 1, 102)]})

    assert reap_orphans(session, client) == 2
    assert _eligibility(session, 100) == "superseded"
    assert _eligibility(session, 101) == "superseded"


def test_retires_rows_when_the_episode_has_no_file_at_all(session):
    # Sonarr reports hasFile=false — discovery skips the episode entirely, so
    # nothing else would ever retire these rows.
    _row(session, 100)
    _row(session, 101)
    client = FakeSonarr({1: [_ep(1, 1, None)]})

    assert reap_orphans(session, client) == 2
    assert _eligibility(session, 100) == "superseded"
    assert _eligibility(session, 101) == "superseded"


def test_does_not_query_series_that_have_no_duplicated_episode(session):
    # Series 2 has one row per episode: nothing suggests an orphan, so it must
    # not cost an API call. This is what keeps the pass targeted (46 of 201
    # series on the real library) instead of a full walk.
    _row(session, 100, parent_id=1)
    _row(session, 101, parent_id=1)
    _row(session, 200, parent_id=2, title="Show B")
    client = FakeSonarr({1: [_ep(1, 1, 101)]})

    reap_orphans(session, client)
    assert client.queried == [1]
    assert _eligibility(session, 200) == "already_h265"


def test_retires_dead_rows_in_non_duplicated_episodes_of_a_walked_series(session):
    # Once a series is walked its live set is authoritative for ALL its
    # episodes, not just the duplicated one — so a lone dead row elsewhere in
    # the same series is retired in the same pass.
    _row(session, 100, season=1, episode=1)
    _row(session, 101, season=1, episode=1)
    _row(session, 103, season=1, episode=3)
    client = FakeSonarr({1: [_ep(1, 1, 101), _ep(1, 3, 104)]})

    assert reap_orphans(session, client) == 2
    assert _eligibility(session, 103) == "superseded"


def test_keeps_live_rows_in_other_episodes_of_a_walked_series(session):
    _row(session, 100, season=1, episode=1)
    _row(session, 101, season=1, episode=1)
    _row(session, 102, season=1, episode=2)
    client = FakeSonarr({1: [_ep(1, 1, 101), _ep(1, 2, 102)]})

    reap_orphans(session, client)
    assert _eligibility(session, 102) == "already_h265"


def test_retired_orphan_is_no_longer_enqueued(session):
    # The actual production symptom: an orphan stuck at needs_transcode is
    # re-enqueued on every run and fails on download, forever.
    _row(session, 100, eligibility="needs_transcode")
    _row(session, 101)
    client = FakeSonarr({1: [_ep(1, 1, 101)]})

    assert enqueue_eligible(session) == 1  # the defect, before reaping
    reap_orphans(session, client)
    assert _eligibility(session, 100) == "superseded"
    assert enqueue_eligible(session) == 0


def test_leaves_radarr_rows_alone(session):
    # discover_radarr walks a pre-filtered movie list, so its "seen" set is not
    # authoritative and per-parent reaping would be wrong there.
    _row(session, 900, source="radarr", parent_id=9, season=None, episode=None)
    _row(session, 901, source="radarr", parent_id=9, season=None, episode=None)
    client = FakeSonarr({})

    assert reap_orphans(session, client) == 0
    assert client.queried == []
    assert _eligibility(session, 900) == "already_h265"


def test_returns_zero_and_queries_nothing_on_a_clean_library(session):
    _row(session, 100, season=1, episode=1)
    _row(session, 102, season=1, episode=2)
    client = FakeSonarr({})

    assert reap_orphans(session, client) == 0
    assert client.queried == []


def test_reaping_twice_retires_nothing_and_costs_no_second_call(session):
    # Already-retired rows must not count towards the duplicate detection,
    # otherwise the same 46 series would be re-queried on every single run.
    _row(session, 100)
    _row(session, 101)
    client = FakeSonarr({1: [_ep(1, 1, 101)]})

    assert reap_orphans(session, client) == 1
    assert reap_orphans(session, client) == 0
    assert client.queried == [1]
