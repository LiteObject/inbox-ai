BEGIN;

CREATE TABLE IF NOT EXISTS email_insights (
    email_uid INTEGER PRIMARY KEY,
    summary TEXT NOT NULL,
    action_items TEXT NOT NULL,
    priority_score INTEGER NOT NULL,
    provider TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    used_fallback INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (email_uid) REFERENCES emails(uid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_email_insights_priority
    ON email_insights(priority_score, generated_at);

COMMIT;
