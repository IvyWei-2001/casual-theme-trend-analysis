"""Local bootstrap entrypoint with no external integration calls."""

from __future__ import annotations

import logging

from .config import load_config
from .logging_config import configure_logging

LOGGER = logging.getLogger(__name__)


def main() -> int:
    """Load local configuration and emit a startup message."""

    config = load_config()
    configure_logging(config.log_level)
    LOGGER.info("bootstrap startup complete: %s", config.app_name)
    return 0
