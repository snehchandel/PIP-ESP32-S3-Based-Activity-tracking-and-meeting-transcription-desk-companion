-- 007: meeting summaries made on this PC (local AI) as soon as a transcript is ready, the Obsidian note each
--      meeting is written to, and a full-text index over transcripts + summaries for search and questions.
ALTER TABLE meetings ADD COLUMN summary_status TEXT NOT NULL DEFAULT 'NONE'; -- NONE|QUEUED|SUMMARIZING|READY|FAILED
ALTER TABLE meetings ADD COLUMN summary_engine TEXT;   -- who wrote it: "local/qwen3:8b", "kimi-k3.1-pro"
ALTER TABLE meetings ADD COLUMN summary_error TEXT;
ALTER TABLE meetings ADD COLUMN vault_note TEXT;       -- the meeting's note, relative to the Obsidian vault
UPDATE meetings SET summary_status = 'READY' WHERE summary_json IS NOT NULL;

-- one row per speaker turn (consecutive lines of one speaker), plus summary rows: title, summary, decisions,
-- action items, topics, notes. Rebuilt per meeting whenever its transcript or summary changes.
CREATE VIRTUAL TABLE IF NOT EXISTS meeting_fts USING fts5(
    meeting_id UNINDEXED, kind UNINDEXED, start_s UNINDEXED, speaker UNINDEXED, text,
    tokenize = 'porter unicode61'
);
