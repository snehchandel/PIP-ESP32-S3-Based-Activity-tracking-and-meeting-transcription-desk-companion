-- 010: which speech model made a meeting's transcript (Parakeet, a Whisper size, or a fine-tuned Parakeet folder).
--      Needed to tell model output from later models' and to measure a fine-tuned model against the user's
--      corrections (raw_text keeps what the model heard, text what the user approved).
ALTER TABLE meetings ADD COLUMN speech_model TEXT;
