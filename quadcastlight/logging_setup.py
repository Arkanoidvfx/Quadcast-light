"""Rotating file log for the resident.

The Discord integration could stop working for weeks without leaving a trace:
the app runs hidden in the tray, and its only status readout was a label in a
window nobody had open. Everything interesting goes to one small log instead.
"""
import logging
import logging.handlers
import os

LOG_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.dirname(os.path.abspath(__file__))),
    "QuadcastLight",
    "logs",
)
LOG_PATH = os.path.join(LOG_DIR, "quadcastlight.log")
MAX_BYTES = 512 * 1024
BACKUP_COUNT = 2

_configured = False


def setup(level=logging.INFO):
    """Attach the rotating file handler once per process."""
    global _configured
    if _configured:
        return logging.getLogger("quadcastlight")
    logger = logging.getLogger("quadcastlight")
    logger.setLevel(level)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    except OSError:
        # A resident that cannot open its log must still run.
        logger.addHandler(logging.NullHandler())
    _configured = True
    return logger


def get(name):
    """Child logger; safe to call before setup()."""
    return logging.getLogger("quadcastlight").getChild(name)
