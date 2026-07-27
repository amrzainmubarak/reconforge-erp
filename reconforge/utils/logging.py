"""Logging helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from reconforge.observability import TelemetryCorrelationFilter


def configure_logging(log_dir: Path | None = None) -> logging.Logger:
    """Configure and return the package logger."""

    logger = logging.getLogger("reconforge")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    stream_handler = logging.StreamHandler()
    stream_handler.addFilter(TelemetryCorrelationFilter())
    stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(stream_handler)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "reconforge.log", encoding="utf-8")
        file_handler.addFilter(TelemetryCorrelationFilter())
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(file_handler)

    return logger
