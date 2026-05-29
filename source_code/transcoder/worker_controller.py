import logging
import threading

from transcoder.models import Job
from transcoder.engine.worker import process_one_job

log = logging.getLogger("transcoder")


class WorkerController:
    """Continuous background worker: drains queued jobs one at a time.

    session_factory: callable returning a new Session (e.g. SessionLocal).
    clients: {"sonarr": SonarrClient, "radarr": RadarrClient}.
    process: per-job processor (injected for tests); defaults to process_one_job.
    idle_timeout: seconds the loop waits on the wake event when the queue is empty.
    """

    def __init__(self, session_factory, clients, process=process_one_job, idle_timeout=5.0):
        self._session_factory = session_factory
        self._clients = clients
        self._process = process
        self._idle_timeout = idle_timeout
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._current_job_id = None
        self._current_cancel = None

    # --- lifecycle ---
    def start(self):
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name="transcode-worker", daemon=True)
        self._thread.start()

    def shutdown(self, timeout=10.0):
        self._stop.set()
        with self._lock:
            if self._current_cancel is not None:
                self._current_cancel.set()
        self._wake.set()
        with self._lock:
            thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def wake(self):
        self._wake.set()

    # --- introspection ---
    @property
    def current_job_id(self):
        with self._lock:
            return self._current_job_id

    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

    # --- cancellation ---
    def request_cancel(self, job_id: int) -> str:
        """Cancel a queued or running job. Returns the resulting state hint."""
        with self._lock:
            if self._current_job_id == job_id and self._current_cancel is not None:
                self._current_cancel.set()
                return "cancelling"
        session = self._session_factory()
        try:
            job = session.get(Job, job_id)
            if job is not None and job.state == "queued":
                job.state = "cancelled"
                session.commit()
                return "cancelled"
            return job.state if job is not None else "missing"
        finally:
            session.close()

    # --- loop ---
    def _next_job_id(self, session):
        job = (
            session.query(Job)
            .filter(Job.state == "queued")
            .order_by(Job.id)
            .first()
        )
        return job.id if job is not None else None

    def _run(self):
        while not self._stop.is_set():
            session = None
            try:
                session = self._session_factory()
                job_id = self._next_job_id(session)
                if job_id is None:
                    # Outer finally closes the session; just idle until woken.
                    self._wake.wait(timeout=self._idle_timeout)
                    self._wake.clear()
                    continue

                job = session.get(Job, job_id)
                if job is None:
                    continue
                cancel_event = threading.Event()
                with self._lock:
                    self._current_job_id = job_id
                    self._current_cancel = cancel_event
                try:
                    # Re-read state under the live transaction: a cancel may have
                    # landed between job selection and registering it as current.
                    session.refresh(job)
                    if job.state == "cancelled":
                        continue
                    self._process(session, job, self._clients, cancel_event=cancel_event)
                except Exception:  # noqa: BLE001 — never let one job kill the loop
                    log.exception("worker: job %s crashed", job_id)
                finally:
                    with self._lock:
                        self._current_job_id = None
                        self._current_cancel = None
            finally:
                if session is not None:
                    session.close()
