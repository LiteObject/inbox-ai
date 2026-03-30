"""Script to clear calendar tokens from the configured database.

Run this script to force a fresh OAuth connection.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).parent


def _resolve_db_path() -> Path:
    if len(sys.argv) > 1:
        configured_path = Path(sys.argv[1]).expanduser()
    else:
        env_path = PROJECT_ROOT / ".env"
        env_values = dotenv_values(env_path) if env_path.exists() else {}
        configured_value = os.environ.get(
            "INBOX_AI_STORAGE__DB_PATH"
        ) or env_values.get("INBOX_AI_STORAGE__DB_PATH")
        configured_path = (
            Path(str(configured_value)).expanduser()
            if configured_value
            else PROJECT_ROOT / "inbox_ai.db"
        )

    if configured_path.is_absolute():
        return configured_path
    return (PROJECT_ROOT / configured_path).resolve()


db_path = _resolve_db_path()

if not db_path.exists():
    print(f"Database not found at {db_path}")
    sys.exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("DELETE FROM user_preferences WHERE key LIKE 'calendar_%'")
deleted_count = cursor.rowcount

conn.commit()
conn.close()

print(f"Cleared {deleted_count} calendar-related preferences from {db_path}")
print("You can now reconnect to Google Calendar with fresh tokens.")
