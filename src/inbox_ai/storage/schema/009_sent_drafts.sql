-- Track when drafts are sent via email
-- This migration adds sent_at timestamp to track outgoing emails

ALTER TABLE drafts ADD COLUMN sent_at TEXT;

-- Index for querying sent drafts
CREATE INDEX IF NOT EXISTS idx_drafts_sent_at ON drafts(sent_at DESC);

-- Index for finding unsent drafts
CREATE INDEX IF NOT EXISTS idx_drafts_unsent ON drafts(sent_at) WHERE sent_at IS NULL;
