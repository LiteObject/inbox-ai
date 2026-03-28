"""Script to clear calendar tokens from the database.

Run this script to force a fresh OAuth connection.
"""

import sqlite3
from pathlib import Path

db_path = Path(__file__).parent / "inbox_ai.db"

if not db_path.exists():
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Clear calendar tokens
cursor.execute("DELETE FROM user_preferences WHERE key LIKE 'calendar_%'")
deleted_count = cursor.rowcount

conn.commit()
conn.close()

print(f"✓ Cleared {deleted_count} calendar-related preferences from database")
print("  You can now reconnect to Google Calendar with fresh tokens")
