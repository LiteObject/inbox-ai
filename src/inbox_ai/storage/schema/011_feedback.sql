-- Persist user feedback and draft outcome metadata for AI quality tracking

ALTER TABLE email_insights ADD COLUMN user_rating INTEGER;

ALTER TABLE drafts ADD COLUMN user_rating INTEGER;
ALTER TABLE drafts ADD COLUMN user_edited INTEGER NOT NULL DEFAULT 0;
ALTER TABLE drafts ADD COLUMN deleted_at TEXT;

CREATE INDEX IF NOT EXISTS idx_email_insights_user_rating
    ON email_insights(user_rating);

CREATE INDEX IF NOT EXISTS idx_drafts_user_rating
    ON drafts(user_rating);

CREATE INDEX IF NOT EXISTS idx_drafts_deleted_at
    ON drafts(deleted_at DESC);
