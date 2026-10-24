from __future__ import annotations
import logging, sys
from logging.handlers import RotatingFileHandler
from src.config import LOGS_DIR

def get_logger(name: str = "cri") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); logger.addHandler(sh)
    try:
        fh = RotatingFileHandler(LOGS_DIR/"app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt); logger.addHandler(fh)
    except OSError:
        pass
    logger.propagate = False
    return logger
