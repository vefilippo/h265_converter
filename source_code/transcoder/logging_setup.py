import logging, datetime as dt, os
import builtins

def init_logging():
    os.makedirs("log", exist_ok=True)
    fname = dt.datetime.now().strftime("log/%Y-%m-%d_%H-%M-%S.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(fname, encoding="utf-8"),
            logging.StreamHandler(),
        ]
    )
    # Redirect print() → logging.info()
    builtins.print = lambda *a, **k: logging.info(" ".join(map(str,a)))
