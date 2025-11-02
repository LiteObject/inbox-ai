-- Migration 005: Ensure mailbox column and index exist
-- This migration is handled specially in Python code

ALTER TABLE emails ADD COLUMN mailbox TEXT;

UPDATE emails SET mailbox = 'INBOX' WHERE mailbox IS NULL;

CREATE INDEX IF NOT EXISTS idx_emails_mailbox ON emails(mailbox);