---
description: "Add a new numbered SQL migration and optional idempotent handler"
mode: "agent"
---

# Add a Schema Migration

## Context

Migrations live in `src/inbox_ai/storage/schema/` as numbered SQL files
(`NNN_description.sql`). They are glob-discovered and applied in sort order by
`SqliteEmailRepository._apply_migrations()`.

## Steps

1. Find the highest existing migration number in `src/inbox_ai/storage/schema/`.
2. Create the next file: `{N+1:03d}_{feature_name}.sql`.
3. Write idempotent SQL where possible (`CREATE TABLE IF NOT EXISTS`,
   `CREATE INDEX IF NOT EXISTS`).
4. If the migration uses `ALTER TABLE ADD COLUMN` (not idempotent in SQLite),
   add a handler method in `storage/sqlite.py`:
   - Add a `_apply_{feature}_migration()` method that checks column existence
     via `PRAGMA table_info` before altering.
   - Register it in `_get_migration_handler()`.
5. Add any corresponding repository methods to `sqlite.py` and update the
   `EmailRepository` Protocol in `core/interfaces.py`.
6. Never modify previously applied migration files.

## Template

```sql
-- {N+1:03d}_{feature_name}.sql
CREATE TABLE IF NOT EXISTS {table_name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_{table_name}_{column}
    ON {table_name}({column});
```
