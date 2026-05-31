import logging
import logging.handlers
import os

from transcoder.log_buffer import log_buffer


def init_logging(component: str = "api", level: int = logging.INFO) -> logging.Logger:
    os.makedirs("log", exist_ok=True)
    fname = f"log/{component}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        fname, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[file_handler, logging.StreamHandler()],
    )
    logger = logging.getLogger("transcoder")
    logger.setLevel(level)
    if log_buffer not in logger.handlers:
        log_buffer.setLevel(level)
        logger.addHandler(log_buffer)
    return logger
