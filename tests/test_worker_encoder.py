import os

from transcoder import encoders
from transcoder.encoders import CPU
from transcoder.engine.worker import process_one_job
from transcoder.models import Job
from transcoder.repo import set_setting

from tests.test_worker import FakeClient, _item, _make_io


def _patch_fs(monkeypatch):
    """Same filesystem stubs the existing worker tests use."""
    monkeypatch.setattr(os.path, "getsize", lambda p: 1000 if "tmp" in p else 400)
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)


def _job(session, item):
    job = Job(media_item_id=item.id, state="queued")
    session.add(job)
    session.commit()
    return job


def _run(session, job, **io_kw):
    _calls, download, upload, convert = _make_io(**io_kw)
    process_one_job(session, job, {"sonarr": FakeClient()},
                    download=download, upload=upload, convert=convert)


def test_worker_uses_auto_resolved_amd_preset(session, monkeypatch):
    _patch_fs(monkeypatch)
    item = _item(session, resolution=1080)
    job = _job(session, item)
    set_setting(session, "encoder_family", "auto")
    encoders.store_capabilities(session, {"vcn", CPU})
    session.commit()

    _run(session, job)
    assert job.preset == "H.265 VCN 1080p"


def test_worker_picks_4k_preset_for_high_resolution(session, monkeypatch):
    _patch_fs(monkeypatch)
    item = _item(session, resolution=2160)
    job = _job(session, item)
    set_setting(session, "encoder_family", "auto")
    encoders.store_capabilities(session, {"vcn", CPU})
    session.commit()

    _run(session, job)
    assert job.preset == "H.265 VCN 2160p 4K"


def test_worker_falls_back_to_cpu_and_logs_loudly(session, monkeypatch):
    _patch_fs(monkeypatch)
    item = _item(session, resolution=1080)
    job = _job(session, item)
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "true")
    # The banner explicitly reported nvenc absent — the only thing that may
    # substitute an encoder away from the user's choice.
    encoders.store_capabilities(session, {"vcn", CPU}, {"nvenc", "qsv"})
    session.commit()

    _run(session, job)
    assert job.preset == "H.265 MKV 1080p30"
    assert "NVIDIA NVENC" in job.log
    assert "slower" in job.log.lower()


def test_worker_does_not_fall_back_when_capabilities_unknown(session, monkeypatch):
    """Unknown is not unavailable: a failed probe must not override the choice."""
    _patch_fs(monkeypatch)
    item = _item(session, resolution=1080)
    job = _job(session, item)
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "true")
    session.commit()  # nothing cached; the autouse stub makes probe return unknown

    _run(session, job)
    assert job.preset == "H.265 NVENC 1080p"


def test_worker_logs_cpu_warning_when_auto_resolves_unknown(session, monkeypatch):
    """auto + unknown capabilities silently lands on CPU x265 (see resolve());
    the log must say so loudly, not claim 'running the configured preset as set'
    (nothing was configured -- the family was never chosen)."""
    _patch_fs(monkeypatch)
    item = _item(session, resolution=1080)
    job = _job(session, item)
    set_setting(session, "encoder_family", "auto")
    session.commit()  # nothing cached; the autouse stub makes probe return unknown

    _run(session, job)
    assert job.preset == "H.265 MKV 1080p30"
    assert "CPU x265" in job.log
    assert "substantially slower" in job.log.lower()


def test_generic_handbrake_failure_does_not_trigger_cpu_fallback(session, monkeypatch):
    """A corrupt input must never silently start an hours-long CPU encode."""
    _patch_fs(monkeypatch)
    item = _item(session, resolution=1080)
    job = _job(session, item)
    set_setting(session, "encoder_family", "vcn")
    encoders.store_capabilities(session, {"vcn", CPU})
    session.commit()

    _run(session, job, fail=True)
    assert job.state == "failed"
    assert job.preset == "H.265 VCN 1080p"
    assert "MKV" not in (job.log or "")


def test_worker_does_not_fall_back_for_a_family_the_banner_never_mentioned(session, monkeypatch):
    """Under-detection must not become substitution. nvenc is missing from the
    cached positives but was never explicitly reported unavailable, so the job
    runs on NVENC as configured instead of starting an hours-long CPU encode."""
    _patch_fs(monkeypatch)
    item = _item(session, resolution=1080)
    job = _job(session, item)
    set_setting(session, "encoder_family", "nvenc")
    set_setting(session, "encoder_fallback_cpu", "true")
    encoders.store_capabilities(session, {"vcn", CPU}, {"qsv"})
    session.commit()

    _run(session, job)
    assert job.preset == "H.265 NVENC 1080p"
    assert "MKV" not in (job.log or "")
