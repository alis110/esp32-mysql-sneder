from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import RuntimeConfig


def configure_logging(config: RuntimeConfig) -> logging.Logger:
    Path(config.log_file).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("plcbridge")
    logger.setLevel(getattr(logging, config.log_level, logging.INFO))
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = RotatingFileHandler(
        config.log_file,
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console)
    return logger
