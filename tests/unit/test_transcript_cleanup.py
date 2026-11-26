"""Transcript clean-up: fillers and stutters go, meaning stays; Whisper's silence phantoms are dropped; old transcripts
can be cleaned in place with the original words kept."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from service.config import Settings
from service.main import create_app
from service.meetings.service import MeetingService
from service.speech.cleanup import clean_text
from service.speech.stt import phantom

from tests.support.meeting_audio import ScriptedSegmentsSTT


def test_fillers_and_repeats_go_meaning_stays() -> None:
    cases = {
        "Um, so we we need the, uh, deck.": "So we need the deck.",
        "The the issue is that that's fine.": "The issue is that that's fine.",
        "No, no, no, no, no, no, no.": "No.",
        "I, I think, you know, it works.": "I think, it works.",
        "We had had enough.": "We had had enough.",
        "It was kind of slow, like, really slow.": "It was kind of slow, really slow.",
        "Yeah, yeah, yeah. Okay okay.": "Yeah. Okay.",
        "Er, the umbrella is here.": "The umbrella is here.",
        "We've, we've entered it.": "We've entered it.",
        "I was, um, going to say": "I was going to say",
        "The human, hmm, is here": "The human is here",
    }
    for raw, want in cases.items():
        assert clean_text(raw) == want, raw
    assert clean_text("Mm-hmm.") == "" and clean_text("Uh.") == "" and clean_text("humm hmm") == ""
    assert clean_text("we use sfmc for casl", ["SFMC", "CASL", "Priya"]) == "we use SFMC for CASL"


def test_whisper_silence_phantoms_are_dropped() -> None:
    seg = lambda text, nsp, lp=-0.3: SimpleNamespace(text=text, no_speech_prob=nsp, avg_logprob=lp)
    assert phantom(seg(" Thank you.", 0.55)) and not phantom(seg(" Thank you.", 0.1))  # a real thanks stays
    assert phantom(seg(" Anything at all", 0.8, -1.2)) and not phantom(seg(" Anything at all", 0.8, -0.2))


def test_meeting_lines_are_cleaned_and_the_raw_words_kept(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import numpy as np
    from service.meetings.service import wav_header
    stt = ScriptedSegmentsSTT([(0.0, 1.0, "Um, so we we need the deck."), (1.2, 1.8, "Mm-hmm."),
                               (2.0, 2.9, "Send it Friday.")])
    svc = MeetingService(manager, tmp_path, "small.en", lambda k, p: None, stt=stt)  # type: ignore[arg-type]
    wav = tmp_path / "a.wav"
    pcm = (np.random.default_rng(0).normal(0, 2000, 16000 * 3)).astype("<i2").tobytes()
    wav.write_bytes(wav_header(len(pcm)) + pcm)
    mid = svc.import_audio(wav, "Sync")
    assert svc.wait_idle(20)
    assert [s["text"] for s in svc.repo.segments(mid)] == ["So we need the deck.", "Send it Friday."]
    raw = manager.db.query("SELECT raw_text FROM meeting_segments WHERE meeting_id=? ORDER BY idx", (mid,))
    assert [r[0] for r in raw] == ["Um, so we we need the deck.", None]  # unchanged lines keep no copy


def test_old_transcripts_can_be_cleaned_and_the_setting_switches_it(tmp_path) -> None:  # type: ignore[no-untyped-def]
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    with TestClient(create_app(s)) as c:
        svcs = c.app.state.services  # type: ignore[attr-defined]
        repo = svcs.meetings.repo
        mid = repo.create("Old", "2026-11-24T15:00:00Z", "America/Toronto", "", status="READY")
        repo.replace_transcript(mid, [{"start_s": 0, "end_s": 1, "text": "The the plan is, uh, fine.", "speaker_key": "S1"},
                                      {"start_s": 1, "end_s": 2, "text": "Uh-huh.", "speaker_key": "S1"},
                                      {"start_s": 2, "end_s": 3, "text": "Ship it.", "speaker_key": "S1"}],
                                [{"key": "S1", "name": "Ana"}])
        assert c.post("/api/v1/meetings/clean-transcripts").json() == {"lines_changed": 1, "lines_removed": 1}
        assert [x["text"] for x in repo.segments(mid)] == ["The plan is fine.", "Ship it."]
        assert c.post("/api/v1/meetings/clean-transcripts").json() == {"lines_changed": 0, "lines_removed": 0}
        assert c.get("/api/v1/settings/meetings").json()["transcript_cleanup"] is True
        assert c.put("/api/v1/settings/meetings", json={"transcript_cleanup": False}).json()["transcript_cleanup"] is False
        assert svcs.stt.cleanup is False


def test_missing_full_stops_are_added_between_sentences() -> None:
    from service.meetings.service import end_sentences
    segs = [{"text": "There is no flag for SMS CASL"}, {"text": "Well, maybe they use an old version"},
            {"text": "and it was never updated"}, {"text": "Right?"}]
    end_sentences(segs)
    assert [s["text"] for s in segs] == ["There is no flag for SMS CASL.", "Well, maybe they use an old version",
                                         "and it was never updated.", "Right?"]
