"""Logging configuration."""

import logging
import os
from config import DISCOGS_USER_AGENT


def setup_logging():
    log_dir = os.path.join(os.path.expanduser("~"), ".metadata_tagger")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "tagger.log")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)

    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    # Redirect third-party loggers to silence noisy output
    logging.getLogger("discogs_client").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
