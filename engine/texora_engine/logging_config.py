"""Shared structured logging for the engine.

Provides a single ``configure_logging`` entry point that wires a rotating file handler
plus a console handler with a structured, machine-greppable formatter. Library code uses
``get_logger`` and never calls ``print``.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGGER_NAME = "texora_engine"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(module)s:%(lineno)d %(message)s"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5


def configure_logging(log_dir: Path, log_level: str = "INFO") -> logging.Logger:
    """Configure and return the shared engine logger.

    Adds a :class:`RotatingFileHandler` writing to ``log_dir/engine.log`` and a console
    handler. Idempotent: repeated calls do not stack duplicate handlers.
    """

    logger = logging.getLogger(_LOGGER_NAME)
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(_LOG_FORMAT)

    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "engine.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the shared engine logger, optionally as a named child."""

    if name is None:
        return logging.getLogger(_LOGGER_NAME)
    return logging.getLogger(_LOGGER_NAME).getChild(name)
