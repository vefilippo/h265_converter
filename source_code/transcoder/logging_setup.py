import datetime as dt
import logging
import os


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
    return logging.getLogger("transcoder")
