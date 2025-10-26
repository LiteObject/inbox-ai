"""Logging configuration helpers."""

from __future__ import annotations

import logging
import logging.config
from typing import Any

from .config import LoggingSettings


def _structured_formatter() -> dict[str, Any]:
    """Return a dictConfig fragment for structured JSON logs."""
    return {
        "format": "{asctime} {levelname} {name} {message}",
        "style": "{",
    }


def _plain_formatter() -> dict[str, Any]:
    """Return a dictConfig fragment for human readable logs."""
    return {
        "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
    }


def configure_logging(settings: LoggingSettings) -> None:
    """Configure application logging according to provided settings."""
    formatter = _structured_formatter() if settings.structured else _plain_formatter()

    dict_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": formatter,
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": settings.level,
            },
        },
        "root": {
            "handlers": ["console"],
            "level": settings.level,
        },
    }

    logging.config.dictConfig(dict_config)


__all__ = ["configure_logging"]
