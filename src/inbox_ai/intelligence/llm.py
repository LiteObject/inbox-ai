"""LLM client abstractions used by intelligence features."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin

import httpx

from inbox_ai.core.config import LlmSettings


class LLMError(RuntimeError):
    """Raised when the LLM provider fails to respond as expected."""


class LLMClient(Protocol):
    """Protocol describing the minimal LLM client behaviour."""

    @property
    def provider_id(self) -> str:
        """Identifier describing the backing model/provider."""
        raise NotImplementedError

    def generate(self, prompt: str) -> str:
        """Return the raw text completion for ``prompt``."""
        raise NotImplementedError


@dataclass(slots=True)
class OllamaClient:
    """Thin synchronous client for the Ollama HTTP API."""

    settings: LlmSettings

    def generate(self, prompt: str) -> str:
        """Send a completion request to the Ollama server."""
        endpoint = _resolve_endpoint(self.settings.base_url)
        payload: dict[str, object] = {
            "model": self.settings.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.settings.temperature},
        }
        if self.settings.max_output_tokens is not None:
            payload["options"] = {
                "temperature": self.settings.temperature,
                "num_predict": self.settings.max_output_tokens,
            }
        data: dict[str, object] | None = None
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = httpx.post(
                    endpoint,
                    json=payload,
                    timeout=self.settings.timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                break
            except httpx.HTTPError as exc:  # pragma: no cover - network dependent
                last_error = exc
            except json.JSONDecodeError as exc:
                raise LLMError("LLM returned invalid JSON") from exc

            if attempt < 3:
                delay = min(2**attempt, 8)
                time.sleep(delay)

        if data is None:
            raise LLMError("LLM request failed after retries") from last_error

        result = data.get("response")
        if not isinstance(result, str):
            raise LLMError("LLM response missing 'response' field")
        return result

    @property
    def provider_id(self) -> str:
        """Return a human readable identifier for the configured model."""
        return f"ollama:{self.settings.model}"


def _resolve_endpoint(base_url: str) -> str:
    trimmed = base_url.rstrip("/") + "/"
    return urljoin(trimmed, "api/generate")


__all__ = ["LLMClient", "OllamaClient", "LLMError"]
