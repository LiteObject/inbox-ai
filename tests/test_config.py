"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from inbox_ai.core.config import load_app_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    """Ensure each test sees a fresh settings instance."""

    load_app_settings.cache_clear()


def test_defaults_loaded_without_env_file() -> None:
    """Default values should be returned when no overrides are present."""

    settings = load_app_settings(include_environment=False)
    assert settings.imap.host == "imap.gmail.com"
    assert settings.storage.db_path == Path("./inbox_ai.db")
    assert settings.sync.batch_size == 50


def test_env_file_overrides(tmp_path: Path) -> None:
    """Values defined in an env file should override defaults."""

    env_file = tmp_path / "test.env"
    env_file.write_text("INBOX_AI_IMAP__HOST=imap.example.com\n", encoding="utf-8")

    settings = load_app_settings(env_file=env_file, include_environment=False)
    assert settings.imap.host == "imap.example.com"
