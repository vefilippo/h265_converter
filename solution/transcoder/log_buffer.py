import datetime as dt
import logging
import threading
from collections import deque


class RingBufferHandler(logging.Handler):
    """Keeps the most recent log records in memory for the /api/logs endpoint.

    Each record is a dict: {seq, ts (ISO-8601 Z), level, message}. seq is a
    monotonic counter so clients can poll incrementally with ?after=<seq>.
    """

    def __init__(self, capacity: int = 500):
        super().__init__()
        self._buf: deque = deque(maxlen=capacity)
        self._seq = 0
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        with self._lock:
            self._seq += 1
            self._buf.append({
                "seq": self._seq,
                "ts": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "level": record.levelname,
                "message": msg,
            })

    def after(self, seq: int) -> list[dict]:
        with self._lock:
            return [r for r in self._buf if r["seq"] > seq]


# Process-wide singleton used by the API.
log_buffer = RingBufferHandler()

# Attach to the "transcoder" logger immediately so records are captured even
# before init_logging() runs (e.g. during tests that skip the app lifespan).
# init_logging() re-sets the level and is guarded against double-attaching.
_transcoder_logger = logging.getLogger("transcoder")
if log_buffer not in _transcoder_logger.handlers:
    log_buffer.setLevel(logging.INFO)
    _transcoder_logger.addHandler(log_buffer)
# Ensure the logger passes INFO records to the handler regardless of root level.
if _transcoder_logger.level == logging.NOTSET:
    _transcoder_logger.setLevel(logging.INFO)
