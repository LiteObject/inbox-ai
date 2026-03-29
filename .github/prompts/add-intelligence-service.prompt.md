---
description: "Add a new intelligence service with LLM integration and deterministic fallback"
mode: "agent"
---

# Add an Intelligence Service

## Context

Intelligence services live in `src/inbox_ai/intelligence/`. Each service wraps
an LLM call with a deterministic fallback, tracks the provider used, and returns
a domain model from `core/models.py`.

## Steps

1. **Define the domain model** in `core/models.py` if one doesn't exist.
2. **Add a prompt builder** in `intelligence/prompts.py`:
   - Use strict JSON-schema instructions so the LLM returns structured output.
   - Include user preferences and thread context where relevant.
   - Keep token budget in mind — summaries over full bodies.
3. **Create the service** in `intelligence/{service_name}.py`:
   - Constructor takes `LLMClient` (optional) and any required dependencies.
   - Primary path: call LLM, parse JSON, map to domain model.
   - Fallback path: deterministic/heuristic logic when LLM is unavailable.
   - Track `provider` and `used_fallback` on every result.
4. **Register in container** (`core/container.py`).
5. **Write tests** in `tests/test_{service_name}.py`:
   - Create a `StubLLM` class implementing the LLM Protocol.
   - Test both LLM and fallback paths.
   - Verify prompt contents via `stub.last_prompt`.

## Template

```python
class MyService:
    def __init__(self, llm_client=None):
        self._llm = llm_client

    def analyze(self, email, body_text):
        if self._llm:
            try:
                response = self._llm.generate(build_my_prompt(email, body_text))
                return self._parse(response)
            except Exception:
                pass
        return self._fallback(email, body_text)

    def _fallback(self, email, body_text):
        # Deterministic logic here
        ...
```
