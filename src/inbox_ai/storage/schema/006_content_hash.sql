-- Migration 006: Add content hash column for caching LLM analysis
-- This migration is handled specially in Python code to avoid duplicate column errors

ALTER TABLE emails ADD COLUMN content_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_emails_content_hash ON emails(content_hash);
