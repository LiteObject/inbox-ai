BEGIN;

CREATE TABLE IF NOT EXISTS email_categories (
    email_uid INTEGER NOT NULL,
    category_key TEXT NOT NULL,
    label TEXT NOT NULL,
    PRIMARY KEY (email_uid, category_key),
    FOREIGN KEY (email_uid) REFERENCES emails(uid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_email_categories_key
    ON email_categories(category_key);

COMMIT;
