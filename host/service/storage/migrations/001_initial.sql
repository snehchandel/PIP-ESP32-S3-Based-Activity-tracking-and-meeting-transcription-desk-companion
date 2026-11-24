-- PIP host schema v1 (spec v6 section 7.2 + D11 device_events)
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT CHECK(status IN ('ACTIVE','SCHEDULED','COMPLETED','ARCHIVED')),
    target_date TEXT NOT NULL,
    timezone TEXT NOT NULL,
    if_then_cue TEXT,
    priority INTEGER DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    duration_min INTEGER NOT NULL CHECK(duration_min BETWEEN 1 AND 60),
    is_starter INTEGER NOT NULL DEFAULT 0,
    remaining_sec INTEGER NOT NULL,
    status TEXT CHECK(status IN ('PENDING','ACTIVE','COMPLETED')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_steps_task ON steps(task_id, position);

CREATE TABLE IF NOT EXISTS parked_tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_text TEXT,
    target_date TEXT,
    status TEXT CHECK(status IN ('PARKED','PROMOTED','DISMISSED')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    due_utc TEXT NOT NULL,
    timezone TEXT NOT NULL,
    if_then_cue TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alarms (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    schedule_kind TEXT CHECK(schedule_kind IN ('ONCE','RECURRING')),
    fire_utc TEXT,
    rrule_days TEXT,
    local_hhmm TEXT NOT NULL,
    timezone TEXT NOT NULL,
    audio_mode TEXT CHECK(audio_mode IN ('WAV','TTS','CHIME')),
    audio_path TEXT,
    tts_script TEXT,
    fallback_chime_id INTEGER NOT NULL DEFAULT 4,
    snooze_min INTEGER NOT NULL DEFAULT 5,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_fired_utc TEXT,
    ack_state TEXT DEFAULT 'IDLE',
    revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS voice_sessions (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    status TEXT,
    transcript TEXT,
    planner_mode TEXT,
    raw_json TEXT,
    needs_confirmation INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_state (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    revision INTEGER NOT NULL DEFAULT 1,
    active_task_id TEXT,
    active_step_id TEXT,
    timer_state TEXT NOT NULL DEFAULT 'STOPPED',
    remaining_ms INTEGER NOT NULL DEFAULT 0,
    last_sync_utc TEXT,
    fw_version TEXT,
    proto_version INTEGER,
    last_boot_id INTEGER,
    last_event_seq INTEGER DEFAULT 0
);
INSERT OR IGNORE INTO device_state(singleton_id) VALUES (1);

CREATE TABLE IF NOT EXISTS device_events (
    boot_id INTEGER NOT NULL,
    event_seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    ref_id TEXT,
    remaining_ms INTEGER,
    ts_epoch INTEGER,
    applied_at TEXT NOT NULL,
    PRIMARY KEY (boot_id, event_seq)
);

CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    level TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    meta_json TEXT
);
