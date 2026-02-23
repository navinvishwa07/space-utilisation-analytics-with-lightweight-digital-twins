"""Structured logging utilities."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from backend.utils.config import get_settings


_LOGGER_INITIALIZED = False


def configure_logging(level: Optional[str] = None) -> None:
    """Configure process-wide logging once.

    Centralizing logger configuration avoids per-module inconsistencies and
    keeps observability formatting stable across layers.
    """

    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return

    settings = get_settings()
    resolved_level = (level or settings.log_level).upper()

    logging.basicConfig(
        level=resolved_level,
        format=(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        ),
        stream=sys.stdout,
    )
    _LOGGER_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for the requested module."""
    configure_logging()
    return logging.getLogger(name)
