-- Migration 007: Add performance indexes for common query patterns

-- Speed up filtering by priority (used in dashboard filters)
CREATE INDEX IF NOT EXISTS idx_email_insights_priority_desc 
ON email_insights(priority_score DESC);

-- Speed up filtering by category (used in dashboard filters)
CREATE INDEX IF NOT EXISTS idx_email_categories_key 
ON email_categories(category_key);

-- Speed up follow-up filtering (used in dashboard and follow-up page)
CREATE INDEX IF NOT EXISTS idx_follow_ups_status_due 
ON follow_ups(status, due_at);

-- Speed up thread lookups (for conversation threading)
CREATE INDEX IF NOT EXISTS idx_emails_thread_id 
ON emails(thread_id);

-- Speed up date-based sorting (composite index for mailbox + date)
CREATE INDEX IF NOT EXISTS idx_emails_mailbox_received 
ON emails(mailbox, received_at DESC);

-- Speed up sender filtering and grouping
CREATE INDEX IF NOT EXISTS idx_emails_sender 
ON emails(sender);

-- Speed up content hash lookups for Phase 1 caching
CREATE INDEX IF NOT EXISTS idx_emails_content_hash 
ON emails(content_hash);

-- Speed up draft lookups by email UID
CREATE INDEX IF NOT EXISTS idx_drafts_email_uid_generated 
ON drafts(email_uid, generated_at DESC);

-- Speed up category joins
CREATE INDEX IF NOT EXISTS idx_email_categories_uid 
ON email_categories(email_uid);

-- Speed up insight lookups with priority filtering
CREATE INDEX IF NOT EXISTS idx_email_insights_priority_generated 
ON email_insights(priority_score DESC, generated_at DESC);
