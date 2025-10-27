BEGIN;

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_uid INTEGER NOT NULL,
    body TEXT NOT NULL,
    provider TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    confidence REAL,
    used_fallback INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (email_uid) REFERENCES emails(uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS follow_ups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_uid INTEGER NOT NULL,
    action TEXT NOT NULL,
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (email_uid) REFERENCES emails(uid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_drafts_email ON drafts(email_uid);
CREATE INDEX IF NOT EXISTS idx_followups_status ON follow_ups(status);
CREATE INDEX IF NOT EXISTS idx_followups_due ON follow_ups(due_at);

COMMIT;
