-- Add Google Calendar sync tracking to follow_ups table
-- Migration: 010_calendar_sync.sql

ALTER TABLE follow_ups 
ADD COLUMN calendar_event_id TEXT DEFAULT NULL;

ALTER TABLE follow_ups 
ADD COLUMN calendar_synced_at TEXT DEFAULT NULL;

-- Index for finding synced follow-ups
CREATE INDEX IF NOT EXISTS idx_follow_ups_calendar_event_id 
ON follow_ups(calendar_event_id) 
WHERE calendar_event_id IS NOT NULL;
