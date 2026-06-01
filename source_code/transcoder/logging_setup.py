import logging
import logging.handlers
import os
import time

from transcoder.log_buffer import log_buffer

_FMT = "%(asctime)s - %(levelname)s - %(message)s"
_ARCHIVE = "log/archive"


def make_daily_handler(path: str, backup_days: int = 30) -> logging.handlers.TimedRotatingFileHandler:
    """Daily-rotating file handler that archives rotated files to log/archive/."""
    os.makedirs(_ARCHIVE, exist_ok=True)
    h = logging.handlers.TimedRotatingFileHandler(
        path, when="midnight", backupCount=backup_days, encoding="utf-8", utc=False
    )
    h.namer = lambda name: os.path.join(_ARCHIVE, os.path.basename(name))
    h.rotator = lambda src, dst: os.rename(src, dst)
    fmt = logging.Formatter(_FMT)
    fmt.converter = time.localtime
    h.setFormatter(fmt)
    return h


def init_logging(component: str = "api", level: int = logging.INFO) -> logging.Logger:
    os.makedirs("log", exist_ok=True)
    file_handler = make_daily_handler(f"log/{component}.log")
    # basicConfig is a no-op if the root logger already has handlers (e.g. uvicorn
    # configures logging before our lifespan runs). Add the file handler directly so
    # it always ends up on the root logger regardless of call order.
    root = logging.getLogger()
    root.setLevel(level)
    already = any(
        isinstance(h, logging.handlers.TimedRotatingFileHandler) and
        getattr(h, "baseFilename", None) == os.path.abspath(f"log/{component}.log")
        for h in root.handlers
    )
    if not already:
        root.addHandler(file_handler)
    logger = logging.getLogger("transcoder")
    logger.setLevel(level)
    if log_buffer not in logger.handlers:
        log_buffer.setLevel(level)
        logger.addHandler(log_buffer)
    return logger
