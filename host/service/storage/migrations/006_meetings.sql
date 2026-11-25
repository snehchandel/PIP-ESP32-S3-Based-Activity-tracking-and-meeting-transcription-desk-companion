-- 006: meeting recordings with speaker-attributed transcripts, remembered voices,
--      parking the active task, and calendar blocks that can be resized.
CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    started_at TEXT NOT NULL,          -- UTC ISO
    ended_at TEXT,
    duration_s REAL NOT NULL DEFAULT 0,
    timezone TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('RECORDING','QUEUED','TRANSCRIBING','READY','FAILED')),
    source TEXT NOT NULL DEFAULT 'DEVICE', -- DEVICE (PIP's mic) | IMPORT (an audio file)
    audio_path TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,  -- 0..1 while transcribing
    error TEXT,
    notes TEXT,
    summary_json TEXT,                 -- optional Kimi summary: {title, summary, decisions, action_items}
    gaps_s REAL NOT NULL DEFAULT 0,    -- audio lost to link drops (filled with silence)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meetings_started ON meetings(started_at);

CREATE TABLE IF NOT EXISTS meeting_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    text TEXT NOT NULL,
    speaker_key TEXT NOT NULL DEFAULT 'S1',
    embedding TEXT                     -- JSON list of voice features (speaker detection / remembered voices)
);
CREATE INDEX IF NOT EXISTS idx_segments_meeting ON meeting_segments(meeting_id, idx);

CREATE TABLE IF NOT EXISTS meeting_speakers (
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    key TEXT NOT NULL,                 -- S1, S2, ...
    name TEXT NOT NULL,                -- "Speaker 01" until the user (or a remembered voice) names it
    profile_id TEXT,
    auto INTEGER NOT NULL DEFAULT 0,   -- 1 = named automatically from a remembered voice
    PRIMARY KEY (meeting_id, key)
);

CREATE TABLE IF NOT EXISTS speaker_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    embedding TEXT NOT NULL,           -- JSON: running mean of raw voice features
    samples INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- a parked active task keeps its steps: the parked note points back at it
ALTER TABLE parked_tasks ADD COLUMN task_id TEXT;
-- calendar block length set by resizing in the app (NULL = sum of the open steps)
ALTER TABLE tasks ADD COLUMN block_min INTEGER;
-- what PIP acts out during a step, chosen by Kimi with the plan (NULL = keyword rules)
ALTER TABLE steps ADD COLUMN activity TEXT;
