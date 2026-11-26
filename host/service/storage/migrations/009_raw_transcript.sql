-- 009: transcript lines are stored cleaned (no "um"/"uh", no stutters, see speech/cleanup.py). The words exactly as
--      Whisper heard them are kept here, so a clean-up can be redone or undone.
ALTER TABLE meeting_segments ADD COLUMN raw_text TEXT;
