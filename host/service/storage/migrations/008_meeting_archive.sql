-- 008: archived meetings stay on the PC (transcript, summary, audio, Obsidian note) but are left out of search,
--      questions, the action-item lists and the calendar until restored.
ALTER TABLE meetings ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
ALTER TABLE meetings ADD COLUMN archived_at TEXT;
