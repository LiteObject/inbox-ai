---
applyTo: "src/inbox_ai/**/*.py, tests/**/*.py"
---

# Backend Architecture Instructions

## Dependency Injection

Services are registered in `core/container.py` via a hand-rolled
`ServiceContainer`. Factories receive the container and instances are cached as
lazy singletons.

```python
container.register("my_service", lambda c: MyService(c.resolve("repository")))
instance = container.resolve("my_service")
```

Do not introduce a DI framework. Keep factories explicit.

## Interfaces & Protocols

All abstractions live in `core/interfaces.py` as Python `Protocol` classes.
Concrete implementations use structural subtyping (duck typing) — no base
classes. When adding a new capability, define the Protocol first, then
implement.

## Repository Pattern

`storage/sqlite.py` implements `EmailRepository`. Key conventions:

- **Upserts** use `ON CONFLICT(uid) DO UPDATE` for idempotency.
- **Soft-delete** via `deleted_at` timestamp. Active queries must exclude
  deleted rows (`WHERE deleted_at IS NULL`).
- **Content-hash caching**: `find_cached_analysis(content_hash)` avoids
  re-analyzing duplicate emails.
- **Context manager**: Repository supports `with` blocks for transaction safety.
- Return domain models from `core/models.py`, not raw dicts or Row objects.

## Schema Migrations

Migrations live in `storage/schema/` as numbered SQL files
(`NNN_description.sql`). They are discovered via glob and applied in sort order.

To add a migration:

1. Create the next numbered file (e.g., `012_my_feature.sql`).
2. If the migration needs idempotency (e.g., `ALTER TABLE ADD COLUMN`), add a
   handler method in `sqlite.py` via `_get_migration_handler()`.
3. Wrap operations in transactions (`with self._connection:`).

Never modify an existing migration file that has been applied.

## Intelligence Layer

The intelligence pipeline follows a common pattern:

1. **Prompt builder** in `intelligence/prompts.py` composes a strict JSON-schema
   prompt with email content, user preferences, and thread context.
2. **Service** (e.g., `SummarizationService`, `DraftingService`) calls the LLM
   client, parses the JSON response, and maps it to domain models.
3. **Fallback chain**: Every service has a deterministic fallback when the LLM
   is unavailable. Never let an LLM failure propagate as a user-visible error.
4. **Audit fields**: Track `provider` ("ollama", "deterministic") and
   `used_fallback` on every generated artifact.

Thread context includes prior subjects/senders/summaries only — never full
bodies — to manage token budget.

## Configuration

`core/config.py` uses hierarchical Pydantic 2 models with env var prefixes:

| Section     | Env Prefix             |
| ----------- | ---------------------- |
| IMAP        | `INBOX_AI_IMAP__`      |
| SMTP        | `INBOX_AI_SMTP__`      |
| LLM         | `INBOX_AI_LLM__`       |
| Storage     | `INBOX_AI_STORAGE__`   |
| Sync        | `INBOX_AI_SYNC__`      |
| Follow-up   | `INBOX_AI_FOLLOW_UP__` |
| User prefs  | `INBOX_AI_USER__`      |
| Calendar    | `INBOX_AI_CALENDAR__`  |

When adding a new config section: create a Pydantic model, nest it in
`AppSettings`, and use a field validator if parsing is needed (e.g.,
comma-separated strings → lists).

## Web Routes

`web/app.py` serves both HTML (Jinja2 templates) and JSON API endpoints.

- HTML routes render templates and redirect on POST.
- JSON API routes live under `/api/` and return structured responses.
- CSRF protection is required for all POST/DELETE routes.
- Response caching uses `@response_cache` decorator with scope-prefixed keys
  (e.g., `"dashboard:"`). Invalidate by prefix after mutations.
- Route handlers use outcome dataclasses (`SyncOutcome`, `DeleteOutcome`, etc.)
  rather than ad-hoc dicts.

## Testing Conventions

- Use **stub classes** that implement the Protocol interface, not
  `unittest.mock.Mock`. Stubs go in the test file, not in a shared fixtures
  module.
- Use pytest's `monkeypatch` fixture to replace module-level functions (e.g.,
  `httpx.post`).
- Use `tmp_path` for ephemeral SQLite databases.
- Use FastAPI `TestClient` for integration tests. Extract CSRF tokens from
  cookies before POST requests.
- Naming: `test_{behavior_under_test}` with long descriptive names.
- Each test creates a fresh database/container — no shared mutable state.
