-- Track locally completed Google Calendar occurrences.
-- Migration: 012_calendar_occurrence_completions.sql

CREATE TABLE IF NOT EXISTS calendar_occurrence_completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calendar_id TEXT NOT NULL,
    occurrence_key TEXT NOT NULL,
    occurrence_start_at TEXT NOT NULL,
    event_id TEXT DEFAULT NULL,
    follow_up_id INTEGER DEFAULT NULL,
    source_type TEXT NOT NULL DEFAULT 'calendar',
    completed_at TEXT NOT NULL,
    UNIQUE(calendar_id, occurrence_key, occurrence_start_at),
    FOREIGN KEY(follow_up_id) REFERENCES follow_ups(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_calendar_occurrence_completions_lookup
ON calendar_occurrence_completions(calendar_id, occurrence_start_at);