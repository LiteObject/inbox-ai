BEGIN;

CREATE TABLE IF NOT EXISTS emails (
    uid INTEGER PRIMARY KEY,
    message_id TEXT,
    thread_id TEXT,
    subject TEXT,
    sender TEXT,
    to_recipients TEXT,
    cc_recipients TEXT,
    bcc_recipients TEXT,
    sent_at TEXT,
    received_at TEXT,
    body_text TEXT,
    body_html TEXT
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_uid INTEGER NOT NULL,
    filename TEXT,
    content_type TEXT,
    size INTEGER,
    FOREIGN KEY (email_uid) REFERENCES emails(uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_state (
    mailbox TEXT PRIMARY KEY,
    last_uid INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id);
CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender);
CREATE INDEX IF NOT EXISTS idx_emails_sent_at ON emails(sent_at);

COMMIT;
