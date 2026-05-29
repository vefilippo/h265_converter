import datetime as dt
import logging
import os

from transcoder.log_buffer import log_buffer


def init_logging(level: int = logging.INFO) -> logging.Logger:
    os.makedirs("log", exist_ok=True)
    fname = dt.datetime.now().strftime("log/%Y-%m-%d_%H-%M-%S.log")
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(fname, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger("transcoder")
    logger.setLevel(level)
    if log_buffer not in logger.handlers:
        log_buffer.setLevel(level)
        logger.addHandler(log_buffer)
    return logger
