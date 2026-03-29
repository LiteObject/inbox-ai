-- Allow follow_ups.email_uid to be NULL so follow-ups can be created
-- from calendar events that have no associated email.
-- SQLite does not support ALTER COLUMN, so we recreate the table.

BEGIN;

CREATE TABLE IF NOT EXISTS follow_ups_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_uid INTEGER,
    action TEXT NOT NULL,
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    calendar_event_id TEXT,
    calendar_synced_at TEXT,
    FOREIGN KEY (email_uid) REFERENCES emails(uid) ON DELETE CASCADE
);

INSERT INTO follow_ups_new (
    id, email_uid, action, due_at, status, created_at,
    completed_at, calendar_event_id, calendar_synced_at
)
SELECT
    id, email_uid, action, due_at, status, created_at,
    completed_at, calendar_event_id, calendar_synced_at
FROM follow_ups;

DROP TABLE follow_ups;

ALTER TABLE follow_ups_new RENAME TO follow_ups;

CREATE INDEX IF NOT EXISTS idx_followups_status ON follow_ups(status);
CREATE INDEX IF NOT EXISTS idx_followups_due ON follow_ups(due_at);
CREATE INDEX IF NOT EXISTS idx_follow_ups_calendar_event_id
ON follow_ups(calendar_event_id)
WHERE calendar_event_id IS NOT NULL;

COMMIT;
