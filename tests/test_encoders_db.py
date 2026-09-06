import json

import pytest

from transcoder import encoders
from transcoder.encoders import (
    CAPABILITIES_KEY, CPU, AUTO, CUSTOM, FAMILIES,
    detect_and_store, get_or_detect_capabilities, load_capabilities,
    migrate_encoder_family, resolve_for_job, store_capabilities,
)
from transcoder.repo import get_setting, set_setting


def test_load_capabilities_returns_unknown_when_absent(session):
    assert load_capabilities(session) == (set(), set(), None)


def test_store_then_load_round_trips(session):
    stamp = store_capabilities(session, {"vcn", CPU}, {"qsv", "nvenc"})
    session.commit()
    available, unavailable, detected_at = load_capabilities(session)
    assert available == {"vcn", CPU}
    assert unavailable == {"qsv", "nvenc"}
    assert detected_at == stamp


def test_load_capabilities_treats_corrupt_json_as_unknown(session):
    set_setting(session, CAPABILITIES_KEY, "not json{")
    session.commit()
    assert load_capabilities(session) == (set(), set(), None)


def test_load_capabilities_reads_an_old_blob_without_negatives(session):
    """Backward compatibility: a cache written before negatives were recorded
    yields an EMPTY unavailable set, i.e. no substitution ever. That is the safe
    direction — the configured family runs as configured."""
    set_setting(session, CAPABILITIES_KEY, json.dumps({
        "available": ["cpu", "vcn"], "detected_at": "2026-01-01T00:00:00+00:00",
    }))
    session.commit()
    available, unavailable, _ = load_capabilities(session)
    assert available == {"vcn", CPU}
    assert unavailable == set()


def test_load_capabilities_rejects_a_non_list_available(session):
    """A bare string parses to a set of CHARACTERS -- {"v","c","n"} -- which is
    truthy and therefore reads as 'capabilities known'. That silently disables
    the unknown-is-not-unavailable guard, so it must be rejected as corrupt."""
    set_setting(session, CAPABILITIES_KEY, json.dumps(
        {"available": "vcn", "detected_at": "2026-01-01T00:00:00+00:00"}))
    session.commit()
    assert load_capabilities(session) == (set(), set(), None)


def test_load_capabilities_rejects_non_string_members(session):
    set_setting(session, CAPABILITIES_KEY, json.dumps(
        {"available": ["vcn", 7], "detected_at": "2026-01-01T00:00:00+00:00"}))
    session.commit()
    assert load_capabilities(session) == (set(), set(), None)


def test_load_capabilities_ignores_a_non_list_unavailable(session):
    """A corrupt NEGATIVE list must degrade to 'no explicit negatives' rather
    than poisoning the whole read: negatives are the only thing that may
    substitute an encoder away from the user's choice."""
    set_setting(session, CAPABILITIES_KEY, json.dumps(
        {"available": ["vcn", "cpu"], "unavailable": "qsv",
         "detected_at": "2026-01-01T00:00:00+00:00"}))
    session.commit()
    available, unavailable, detected_at = load_capabilities(session)
    assert available == {"vcn", "cpu"}
    assert unavailable == set()
    assert detected_at == "2026-01-01T00:00:00+00:00"


def test_load_capabilities_nulls_detected_at_when_available_is_empty(session):
    """empty-set-means-unknown must be total: a timestamp beside an empty set
    would let a caller conclude 'we successfully detected nothing'."""
    set_setting(session, CAPABILITIES_KEY, json.dumps(
        {"available": [], "detected_at": "2026-01-01T00:00:00+00:00"}))
    session.commit()
    assert load_capabilities(session) == (set(), set(), None)


def test_detect_and_store_persists_probe_result(session, monkeypatch):
    monkeypatch.setattr(encoders, "probe", lambda cli, **kw: ({"vcn", CPU}, {"nvenc"}))
    available, unavailable, detected_at = detect_and_store(session, "hb.exe")
    session.commit()
    assert available == {"vcn", CPU}
    assert unavailable == {"nvenc"}
    assert detected_at is not None
    assert load_capabilities(session)[:2] == ({"vcn", CPU}, {"nvenc"})


def test_detect_and_store_does_not_cache_a_failed_probe(session, monkeypatch):
    monkeypatch.setattr(encoders, "probe", lambda cli, **kw: (set(), set()))
    available, unavailable, detected_at = detect_and_store(session, "hb.exe")
    session.commit()
    assert (available, unavailable, detected_at) == (set(), set(), None)
    assert get_setting(session, CAPABILITIES_KEY) is None


def test_get_or_detect_uses_cache_without_probing(session, monkeypatch):
    store_capabilities(session, {"nvenc", CPU})
    session.commit()

    def boom(*a, **k):
        raise AssertionError("probe must not run when a cache exists")

    monkeypatch.setattr(encoders, "probe", boom)
    assert get_or_detect_capabilities(session, "hb.exe")[:2] == ({"nvenc", CPU}, set())


def test_get_or_detect_probes_once_and_caches_when_absent(session, monkeypatch):
    calls = {"n": 0}

    def fake_probe(cli, **kw):
        calls["n"] += 1
        return {"qsv", CPU}, {"vcn"}

    monkeypatch.setattr(encoders, "probe", fake_probe)
    assert get_or_detect_capabilities(session, "hb.exe")[:2] == ({"qsv", CPU}, {"vcn"})
    session.commit()
    assert get_or_detect_capabilities(session, "hb.exe")[:2] == ({"qsv", CPU}, {"vcn"})
    assert calls["n"] == 1


def test_resolve_for_job_uses_auto_and_cached_capabilities(session):
    set_setting(session, "encoder_family", AUTO)
    store_capabilities(session, {"vcn", CPU})
    session.commit()
    r = resolve_for_job(session)
    assert r.family == "vcn"
    assert r.preset_1080 == "H.265 VCN 1080p"


def test_resolve_for_job_falls_back_to_cpu_for_an_explicitly_unavailable_family(session):
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "true")
    store_capabilities(session, {"vcn", CPU}, {"nvenc", "qsv"})
    session.commit()
    r = resolve_for_job(session)
    assert r.family == CPU
    assert r.requested == "nvenc"
    assert r.substituted is True


def test_resolve_for_job_does_not_substitute_a_family_the_banner_never_mentioned(session):
    """Under-detection must not become substitution: nvenc is absent from the
    cached positives but was never explicitly reported unavailable."""
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "true")
    store_capabilities(session, {"vcn", CPU}, {"qsv"})
    session.commit()
    r = resolve_for_job(session)
    assert r.family == "nvenc"
    assert r.substituted is False


def test_resolve_for_job_never_substitutes_from_a_pre_negatives_cache(session):
    """An old cached blob has no "unavailable" key, so nothing is known to be
    absent and the configured family runs as configured."""
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "true")
    set_setting(session, CAPABILITIES_KEY, json.dumps({
        "available": ["cpu", "vcn"], "detected_at": "2026-01-01T00:00:00+00:00",
    }))
    session.commit()
    r = resolve_for_job(session)
    assert r.family == "nvenc"
    assert r.substituted is False


def test_resolve_for_job_honours_fallback_disabled(session):
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "false")
    store_capabilities(session, {"vcn", CPU}, {"nvenc"})
    session.commit()
    r = resolve_for_job(session)
    assert r.family == "nvenc"
    assert r.substituted is False


def test_resolve_for_job_custom_uses_stored_preset_strings(session):
    set_setting(session, "encoder_family", CUSTOM)
    set_setting(session, "handbrake_preset_1080", "Mine 1080")
    set_setting(session, "handbrake_preset_4k", "Mine 4K")
    store_capabilities(session, {"vcn", CPU})
    session.commit()
    r = resolve_for_job(session)
    assert (r.preset_1080, r.preset_4k) == ("Mine 1080", "Mine 4K")


def test_migrate_marks_fresh_install_as_auto(session):
    # Fresh install: no presets have been seeded yet.
    assert migrate_encoder_family(session) == AUTO
    session.commit()
    assert get_setting(session, "encoder_family") == AUTO


def test_migrate_infers_family_from_existing_presets(session):
    set_setting(session, "handbrake_preset_1080", "H.265 NVENC 1080p")
    set_setting(session, "handbrake_preset_4k", "H.265 NVENC 2160p 4K")
    session.commit()
    assert migrate_encoder_family(session) == "nvenc"
    session.commit()
    assert get_setting(session, "encoder_family") == "nvenc"


def test_migrate_preserves_hand_tuned_presets_as_custom(session):
    set_setting(session, "handbrake_preset_1080", "Fast 1080p30")
    set_setting(session, "handbrake_preset_4k", "Fast 2160p60")
    session.commit()
    assert migrate_encoder_family(session) == CUSTOM


def test_migrate_is_idempotent_and_never_overwrites(session):
    set_setting(session, "encoder_family", "qsv")
    set_setting(session, "handbrake_preset_1080", "H.265 NVENC 1080p")
    session.commit()
    assert migrate_encoder_family(session) is None
    assert get_setting(session, "encoder_family") == "qsv"


def test_migrate_honours_encoder_family_from_config_on_fresh_install(session, monkeypatch):
    """ENCODER_FAMILY is documented .env configuration. The backfill runs at
    startup on every entry point before anything reads the family, so if it
    hardcodes AUTO here the env value can never take effect on any install that
    has ever booted -- get_effective() would always find the DB row."""
    from transcoder.config import settings as cfg
    monkeypatch.setattr(cfg, "ENCODER_FAMILY", CUSTOM)
    assert migrate_encoder_family(session) == CUSTOM
    session.commit()
    assert get_setting(session, "encoder_family") == CUSTOM


def test_migrate_falls_back_to_auto_when_config_family_is_blank(session, monkeypatch):
    from transcoder.config import settings as cfg
    monkeypatch.setattr(cfg, "ENCODER_FAMILY", "")
    assert migrate_encoder_family(session) == AUTO


@pytest.mark.parametrize("bogus", ["amd", "vce", "nvidia", "AUTO", "  ", "VCN"])
def test_migrate_normalises_or_rejects_an_unrecognised_config_family(
    session, monkeypatch, bogus
):
    """A typo in ENCODER_FAMILY must never become the stored family.

    Storing it unvalidated is sticky and actively harmful: the row now exists so
    the env is never consulted again, and resolve() treats any unknown family as
    CUSTOM -- handing back the hardcoded NVENC presets that seed_settings_from_env
    just wrote. On an AMD box that fails every single job, which is the exact
    failure this feature exists to remove.
    """
    from transcoder.config import settings as cfg

    monkeypatch.setattr(cfg, "ENCODER_FAMILY", bogus)
    written = migrate_encoder_family(session)
    session.commit()
    # Case differences are a user typo we can safely honour; anything we cannot
    # map to a real family must degrade to AUTO, which detects the truth.
    expected = bogus.strip().lower()
    if expected not in FAMILIES and expected not in (AUTO, CUSTOM):
        expected = AUTO
    assert written == expected
    assert get_setting(session, "encoder_family") == expected


def test_migrate_ignores_config_family_for_an_upgraded_install(session, monkeypatch):
    """An existing install's presets are the stronger signal: the env default
    must not silently retag a deliberate NVIDIA setup."""
    from transcoder.config import settings as cfg
    monkeypatch.setattr(cfg, "ENCODER_FAMILY", "vcn")
    set_setting(session, "handbrake_preset_1080", "H.265 NVENC 1080p")
    set_setting(session, "handbrake_preset_4k", "H.265 NVENC 2160p 4K")
    session.commit()
    assert migrate_encoder_family(session) == "nvenc"
