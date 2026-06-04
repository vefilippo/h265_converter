from transcoder.scheduler import SchedulerController


def test_registered_job_tolerates_event_loop_stall():
    """The nightly job must not be silently dropped when the event loop is
    a few seconds late (APScheduler's default misfire_grace_time is 1s, which
    caused the 1am run to be skipped). It should also coalesce missed runs."""
    controller = SchedulerController()
    controller.set_job_fn(lambda: None)
    controller._register("0 01 * * *")

    job = controller._scheduler.get_job("scheduled_scan")
    assert job is not None
    # Generous grace window so a brief stall doesn't drop the run.
    assert job.misfire_grace_time is None or job.misfire_grace_time >= 600
    assert job.coalesce is True
