"""Minimal standard-library logging setup."""

from __future__ import annotations

import logging
from typing import Final

DEFAULT_LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with a standard stream handler."""

    level_name = level.upper()
    numeric_level = logging.getLevelNamesMapping().get(level_name)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Unsupported log level: {level!r}")

    logging.basicConfig(level=numeric_level, format=DEFAULT_LOG_FORMAT)
    logging.getLogger().setLevel(numeric_level)
