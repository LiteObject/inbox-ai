---
description: "Add a new FastAPI route (HTML or JSON API) with CSRF, caching, and outcome pattern"
mode: "agent"
---

# Add a New Route

## Context

Routes are defined in `src/inbox_ai/web/app.py`. The app serves HTML via Jinja2
templates and JSON via `/api/` prefixed endpoints. All POST/DELETE routes require
CSRF tokens. Response caching uses scope-prefixed keys.

## Steps

1. Decide if the route is HTML (renders a template) or JSON API (`/api/` prefix).
2. Define an outcome dataclass if the route mutates state (follow the
   `SyncOutcome` / `DeleteOutcome` pattern in app.py).
3. Add the route handler function with appropriate HTTP method decorator.
4. For POST routes: include CSRF validation via `csrf_protector.validate()`.
5. For cached GET routes: add `@response_cache("scope:")` and invalidate after
   related mutations.
6. Resolve services from the container — do not instantiate directly.
7. Add a corresponding integration test in `tests/test_web_app.py` using
   `TestClient`.

## Template

```python
@app.post("/api/{resource}")
async def handle_{resource}_action(request: Request):
    csrf_protector.validate(request)
    service = container.resolve("{service_key}")
    outcome = service.do_action(...)
    response_cache.invalidate("{scope}")
    return outcome.__dict__
```
