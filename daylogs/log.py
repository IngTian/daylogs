"""Rotating file logging.

A TUI owns the terminal, so stdout is unavailable while the app runs. This
file handler is the only place an error can surface. Logs deliberately live
outside the iCloud-synced data root — high-churn diagnostic data has no
business being replicated.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_MAX_BYTES = 1_000_000
_BACKUPS = 3


def log_dir(root: Path | None = None) -> Path:
    return (root or Path.home() / ".daylogs") / "logs"


def setup_logging(root: Path | None = None, level: int = logging.INFO) -> Path:
    d = log_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "daylogs.log"
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)
    return path
