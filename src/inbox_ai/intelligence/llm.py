"""LLM client abstractions used by intelligence features."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urljoin

import httpx

from inbox_ai.core.config import LlmSettings

_MAX_RETRY_ATTEMPTS = 3
_CIRCUIT_BREAKER_THRESHOLD = 3


class LLMError(RuntimeError):
    """Raised when the LLM provider fails to respond as expected."""


class LLMClient(Protocol):
    """Protocol describing the minimal LLM client behaviour."""

    @property
    def provider_id(self) -> str:
        """Identifier describing the backing model/provider."""
        raise NotImplementedError

    def generate(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Return the raw text completion for ``prompt``."""
        raise NotImplementedError


@dataclass(slots=True)
class OllamaClient:
    """Thin synchronous client for the Ollama HTTP API."""

    settings: LlmSettings
    _consecutive_failures: int = field(default=0, init=False, repr=False)
    _circuit_open: bool = field(default=False, init=False, repr=False)

    def generate(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send a completion request to the Ollama server."""
        if self._circuit_open:
            raise LLMError("LLM circuit breaker is open")

        endpoint = _resolve_endpoint(self.settings.base_url)
        options: dict[str, object] = {
            "temperature": (
                self.settings.temperature if temperature is None else temperature
            )
        }
        resolved_max_tokens = (
            self.settings.max_output_tokens if max_tokens is None else max_tokens
        )
        if resolved_max_tokens is not None:
            options["num_predict"] = resolved_max_tokens

        payload: dict[str, object] = {
            "model": self.settings.model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        data: dict[str, object] | None = None
        last_error: Exception | None = None
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            try:
                response = httpx.post(
                    endpoint,
                    json=payload,
                    timeout=self.settings.timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                break
            except httpx.HTTPStatusError as exc:  # pragma: no cover - network dependent
                status_code = exc.response.status_code
                if 400 <= status_code < 500:
                    self._record_failure()
                    raise LLMError(
                        f"LLM request failed with non-retryable status {status_code}"
                    ) from exc
                last_error = exc
            except httpx.RequestError as exc:  # pragma: no cover - network dependent
                last_error = exc
            except json.JSONDecodeError as exc:
                self._record_failure()
                raise LLMError("LLM returned invalid JSON") from exc

            if attempt < _MAX_RETRY_ATTEMPTS:
                delay = min(2**attempt, 8)
                time.sleep(delay)

        if data is None:
            self._record_failure()
            if self._circuit_open:
                raise LLMError(
                    "LLM circuit breaker opened after repeated failures"
                ) from last_error
            raise LLMError("LLM request failed after retries") from last_error

        self._reset_failures()

        result = data.get("response")
        if not isinstance(result, str):
            raise LLMError("LLM response missing 'response' field")
        return result

    def reset_circuit_breaker(self) -> None:
        """Clear failure tracking before a new sync batch begins."""
        self._reset_failures()

    @property
    def provider_id(self) -> str:
        """Return a human readable identifier for the configured model."""
        return f"ollama:{self.settings.model}"

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
            self._circuit_open = True

    def _reset_failures(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open = False


def _resolve_endpoint(base_url: str) -> str:
    trimmed = base_url.rstrip("/") + "/"
    return urljoin(trimmed, "api/generate")


__all__ = ["LLMClient", "OllamaClient", "LLMError"]
