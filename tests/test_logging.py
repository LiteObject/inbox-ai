"""Tests for logging utilities."""

from __future__ import annotations

import logging

from inbox_ai.core.config import LoggingSettings
from inbox_ai.core.logging import configure_logging


def test_configure_logging_sets_root_level() -> None:
    """configure_logging should set the root logger level according to settings."""

    settings = LoggingSettings(level="DEBUG", structured=False)
    configure_logging(settings)
    assert logging.getLogger().level == logging.DEBUG
