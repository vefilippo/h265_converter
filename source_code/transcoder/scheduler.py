import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("transcoder")


class SchedulerController:
    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._job_fn = None

    def set_job_fn(self, fn):
        self._job_fn = fn

    def start(self, cron: str | None, run_at_startup: bool) -> None:
        self._scheduler.start()
        if cron:
            self._register(cron)
        if run_at_startup and self._job_fn:
            import asyncio
            asyncio.ensure_future(self._job_fn())

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def reschedule(self, cron: str | None) -> None:
        self._scheduler.remove_all_jobs()
        if cron:
            self._register(cron)

    def next_run(self) -> str | None:
        job = self._scheduler.get_job("scheduled_scan")
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
        return None

    def _register(self, cron: str) -> None:
        minute, hour, day, month, dow = cron.strip().split()
        trigger = CronTrigger(
            minute=minute, hour=hour, day=day, month=month, day_of_week=dow
        )
        self._scheduler.add_job(
            self._job_fn, trigger, id="scheduled_scan", replace_existing=True
        )

    @staticmethod
    def validate_cron(cron: str) -> bool:
        try:
            parts = cron.strip().split()
            if len(parts) != 5:
                return False
            minute, hour, day, month, dow = parts
            CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow)
            return True
        except Exception:
            return False
