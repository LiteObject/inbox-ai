"""Application configuration models and loader utilities."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from dotenv import dotenv_values
from pydantic import BaseModel, Field


class ImapSettings(BaseModel):
    """Settings controlling IMAP connectivity."""

    host: str = Field(default="imap.gmail.com", description="IMAP hostname")
    port: int = Field(default=993, description="IMAP port, typically 993 for SSL")
    username: str | None = Field(default=None, description="Account username")
    app_password: str | None = Field(default=None, description="Gmail app password")
    mailbox: str = Field(default="INBOX", description="Mailbox to monitor")
    use_ssl: bool = Field(default=True, description="Whether to enforce SSL")


class LlmSettings(BaseModel):
    """Settings for the local LLM provider."""

    base_url: str = Field(
        default="http://localhost:11434", description="Ollama server URL"
    )
    model: str = Field(default="gpt-oss:20b", description="Model identifier")
    timeout_seconds: int = Field(
        default=30, description="Request timeout for LLM calls"
    )
    temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Sampling temperature for LLM completions",
    )
    max_output_tokens: int | None = Field(
        default=512,
        ge=32,
        description="Maximum tokens to request from the provider",
    )
    fallback_enabled: bool = Field(
        default=True, description="Use deterministic fallback when LLM fails"
    )


class StorageSettings(BaseModel):
    """Settings for local persistence."""

    db_path: Path = Field(
        default=Path("./inbox_ai.db"), description="SQLite database path"
    )


class LoggingSettings(BaseModel):
    """Logging preferences."""

    level: str = Field(default="INFO", description="Root logging level")
    structured: bool = Field(
        default=False, description="Toggle JSON structured logging"
    )


class SyncSettings(BaseModel):
    """Settings controlling fetch cadence and bounds."""

    batch_size: int = Field(
        default=50, ge=1, description="Messages fetched per IMAP batch"
    )
    max_messages: int | None = Field(
        default=None, description="Hard cap for messages processed in a cycle"
    )


class AppSettings(BaseModel):
    """Aggregated application configuration."""

    imap: ImapSettings = Field(default_factory=ImapSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)


ENV_PREFIX = "INBOX_AI_"


def _normalize_key(raw_key: str) -> list[str]:
    """Convert an environment variable key into a nested attribute path."""
    trimmed = raw_key.removeprefix(ENV_PREFIX)
    return [segment.lower() for segment in trimmed.split("__") if segment]


def _merge_into_tree(tree: dict[str, Any], path: list[str], value: Any) -> None:
    """Assign a value to a nested dictionary given a path."""
    cursor = tree
    for segment in path[:-1]:
        next_node = cursor.setdefault(segment, {})
        cursor = cast(dict[str, Any], next_node)
    cursor[path[-1]] = value


def _collect_env_values(env_file: Path | str | None) -> dict[str, Any]:
    """Load configuration values from environment variables and optional file."""
    collected: dict[str, Any] = {}

    file_values = {}
    if env_file:
        env_path = Path(env_file)
        if env_path.is_file():
            file_values = {
                key: value
                for key, value in dotenv_values(env_path).items()
                if key and key.startswith(ENV_PREFIX)
            }

    env_values = {
        key: value for key, value in os.environ.items() if key.startswith(ENV_PREFIX)
    }

    combined: dict[str, Any] = {**file_values, **env_values}

    for key, value in combined.items():
        path = _normalize_key(key)
        if not path:
            continue
        normalized_value: Any = value
        if isinstance(value, str) and value == "":
            normalized_value = None
        elif isinstance(value, str):
            lowercase_value = value.lower()
            if lowercase_value == "true":
                normalized_value = True
            elif lowercase_value == "false":
                normalized_value = False
        _merge_into_tree(collected, path, normalized_value)

    return collected


@lru_cache(maxsize=1)
def load_app_settings(
    env_file: Path | str | None = None, **overrides: Any
) -> AppSettings:
    """Load application settings, applying env files and overrides."""
    collected = _collect_env_values(env_file)
    if overrides:
        collected.update(overrides)
    return AppSettings.model_validate(collected)


__all__ = [
    "AppSettings",
    "ImapSettings",
    "LlmSettings",
    "LoggingSettings",
    "StorageSettings",
    "SyncSettings",
    "load_app_settings",
]
