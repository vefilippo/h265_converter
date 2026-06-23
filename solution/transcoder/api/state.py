"""Process-wide singletons for the API: the worker controller and scan status."""
import datetime as dt
import threading

from transcoder.config import settings
from transcoder.db import SessionLocal
from transcoder.sonarr_client import SonarrClient
from transcoder.radarr_client import RadarrClient
from transcoder.worker_controller import WorkerController


def build_clients() -> dict:
    from transcoder.repo import get_effective
    with SessionLocal() as db:
        return {
            "sonarr": SonarrClient(
                get_effective(db, "sonarr_url", settings.SONARR_URL),
                get_effective(db, "sonarr_api_key", settings.SONARR_API_KEY),
            ),
            "radarr": RadarrClient(
                get_effective(db, "radarr_url", settings.RADARR_URL),
                get_effective(db, "radarr_api_key", settings.RADARR_API_KEY),
            ),
        }


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class ScanStatus:
    """In-memory status of the most recent scan (single-user app)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.state = "idle"          # idle | running | done | error
        self.detail = {}             # arbitrary counts / message
        self.started_at = None       # ISO-8601 when the current/last scan began
        self.finished_at = None      # ISO-8601 when it reached done/error

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self.state,
                "detail": dict(self.detail),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def set(self, state: str, **detail):
        with self._lock:
            self.state = state
            self.detail = detail
            if state in ("done", "error"):
                self.finished_at = _now_iso()

    def try_start(self) -> bool:
        """Atomically transition to 'running' if not already running.

        Returns True if this caller acquired the scan slot, False if a scan is
        already running. Closes the check-then-set race in the scan endpoint.
        """
        with self._lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.detail = {}
            self.started_at = _now_iso()
            self.finished_at = None
            return True

    @property
    def running(self) -> bool:
        with self._lock:
            return self.state == "running"


# Singletons (constructed once at import).
controller = WorkerController(SessionLocal, build_clients())
scan_status = ScanStatus()

from transcoder.scheduler import SchedulerController
scheduler: SchedulerController = SchedulerController()
