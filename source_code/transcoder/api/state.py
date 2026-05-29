"""Process-wide singletons for the API: the worker controller and scan status."""
import threading

from transcoder.config import settings
from transcoder.db import SessionLocal
from transcoder.sonarr_client import SonarrClient
from transcoder.radarr_client import RadarrClient
from transcoder.worker_controller import WorkerController


def build_clients() -> dict:
    return {
        "sonarr": SonarrClient(settings.SONARR_URL, settings.SONARR_API_KEY),
        "radarr": RadarrClient(settings.RADARR_URL, settings.RADARR_API_KEY),
    }


class ScanStatus:
    """In-memory status of the most recent scan (single-user app)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.state = "idle"          # idle | running | done | error
        self.detail = {}             # arbitrary counts / message

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self.state, "detail": dict(self.detail)}

    def set(self, state: str, **detail):
        with self._lock:
            self.state = state
            self.detail = detail

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
            return True

    @property
    def running(self) -> bool:
        with self._lock:
            return self.state == "running"


# Singletons (constructed once at import).
controller = WorkerController(SessionLocal, build_clients())
scan_status = ScanStatus()
