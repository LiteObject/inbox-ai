"""Tests for the Ollama LLM client."""

from __future__ import annotations

import httpx
import pytest

from inbox_ai.core.config import LlmSettings
from inbox_ai.intelligence.llm import LLMError, OllamaClient


def _settings() -> LlmSettings:
    return LlmSettings(
        base_url="http://localhost:11434",
        model="test-model",
        timeout_seconds=5,
        temperature=0.2,
        max_output_tokens=256,
    )


def test_ollama_client_accepts_per_call_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, *, json: dict[str, object], timeout: int) -> httpx.Response:
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"response": "ok"}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    client = OllamaClient(_settings())

    response = client.generate("hello", temperature=0.7, max_tokens=128)

    assert response == "ok"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["timeout"] == 5
    assert captured["json"] == {
        "model": "test-model",
        "prompt": "hello",
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 128},
    }


def test_ollama_client_fails_fast_on_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_post(url: str, *, json: dict[str, object], timeout: int) -> httpx.Response:
        nonlocal calls
        del json, timeout
        calls += 1
        request = httpx.Request("POST", url)
        return httpx.Response(401, json={"error": "unauthorized"}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    client = OllamaClient(_settings())

    with pytest.raises(LLMError, match="non-retryable status 401"):
        client.generate("hello")

    assert calls == 1


def test_ollama_client_opens_circuit_after_repeated_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_post(url: str, *, json: dict[str, object], timeout: int) -> httpx.Response:
        nonlocal calls
        del json, timeout
        calls += 1
        request = httpx.Request("POST", url)
        return httpx.Response(503, json={"error": "unavailable"}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr("inbox_ai.intelligence.llm.time.sleep", lambda _: None)

    client = OllamaClient(_settings())

    for _ in range(3):
        with pytest.raises(LLMError):
            client.generate("hello")

    with pytest.raises(LLMError, match="circuit breaker is open"):
        client.generate("hello")

    assert calls == 9


def test_ollama_client_reset_circuit_breaker_allows_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    should_fail = True

    def fake_post(url: str, *, json: dict[str, object], timeout: int) -> httpx.Response:
        nonlocal calls, should_fail
        del json, timeout
        calls += 1
        request = httpx.Request("POST", url)
        if should_fail:
            return httpx.Response(503, json={"error": "unavailable"}, request=request)
        return httpx.Response(200, json={"response": "recovered"}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr("inbox_ai.intelligence.llm.time.sleep", lambda _: None)

    client = OllamaClient(_settings())

    for _ in range(3):
        with pytest.raises(LLMError):
            client.generate("hello")

    client.reset_circuit_breaker()
    should_fail = False

    assert client.generate("hello") == "recovered"
    assert calls == 10
