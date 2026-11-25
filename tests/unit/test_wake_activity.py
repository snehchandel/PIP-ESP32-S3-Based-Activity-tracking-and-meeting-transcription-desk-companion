"""Wake word, then the activity's name: "Hi ESP... Meeting" / "Hi ESP, alarms, wake me at 7" (decided on the PC)."""
from __future__ import annotations

import struct
import time
from pathlib import Path

import numpy as np
import pytest
from service.device.link import DeviceLink
from service.meetings.service import MeetingService
from service.planner.local_rule import LocalRulePlanner
from service.protocol import Frame, FrameType
from service.speech import spoken_activity
from service.speech.pipeline import AUTO, CANCELLED, VoicePipeline

from tests.support.meeting_audio import ScriptedSegmentsSTT


@pytest.mark.parametrize(("text", "act", "rest"), [
    ("Meeting.", "MEETING", ""),
    ("Meeting", "MEETING", ""),
    ("Um, meeting.", "MEETING", ""),
    ("Hi ESP. Record a meeting.", "MEETING", ""),
    ("Alarms, wake me at 7 tomorrow.", "ALARMS", "wake me at 7 tomorrow."),
    ("Alarm. Wake me at six thirty.", "ALARMS", "Wake me at six thirty."),
    ("Calendar. Dentist on Thursday at 2.", "CALENDAR", "Dentist on Thursday at 2."),
    ("Brain dump. I need to sort the garage.", "BRAIN_DUMP", "I need to sort the garage."),
    ("Focus, pause the timer.", "FOCUS", "pause the timer."),
    ("Meeting with Bob is moved to 3.", None, "Meeting with Bob is moved to 3."),
    ("I have a meeting at 3.", None, "I have a meeting at 3."),
    ("Calendaring is hard.", None, "Calendaring is hard."),
    ("", None, ""),
])
def test_spoken_activity_names(text, act, rest) -> None:  # type: ignore[no-untyped-def]
    assert spoken_activity.parse(text) == (act, rest)


def _speech(seconds: float, tail_quiet: float = 0.0) -> bytes:
    rng = np.random.default_rng(1)
    loud = (rng.normal(0, 4000, int(seconds * 16000))).astype("<i2").tobytes()
    return loud + bytes(int(tail_quiet * 16000) * 2)


def test_trailing_pause_is_detected() -> None:
    assert spoken_activity.ends_quiet(_speech(1.2, 0.6))
    assert not spoken_activity.ends_quiet(_speech(1.8))


class PhasedSTT:  # test-only double: what Whisper "hears" in the first seconds vs. in the whole message
    status = "TEST"

    def __init__(self, early: str, full: str) -> None:
        self.early, self.full, self.calls, self.final = early, full, 0, False

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        self.calls += 1
        return self.full if self.final else self.early


def _rig(manager, tmp_path: Path, stt):  # type: ignore[no-untyped-def]
    events: list[tuple[str, dict]] = []  # type: ignore[type-arg]
    voice = VoicePipeline(manager, stt, lambda: LocalRulePlanner(), lambda k, p: events.append((k, p)))
    voice.meetings = MeetingService(manager, tmp_path, "small.en", lambda k, p: events.append((k, p)),
                                    stt=ScriptedSegmentsSTT([(0.0, 1.0, "Hello everyone.")]))  # type: ignore[arg-type]
    return voice, DeviceLink(manager, None, voice, lambda k, p: None), events


def _send(link, stream: int, pcm: bytes, first: int = 0, start: bool = True) -> None:  # type: ignore[no-untyped-def]
    if start:
        link._dispatch(Frame(FrameType.AUDIO_START, 1, 1, struct.pack("<IHBBHH", stream, 16000, 1, 16, 600, AUTO)))
    for k in range(len(pcm) // 640):
        link._dispatch(Frame(FrameType.AUDIO_DATA, 0, 2, struct.pack("<IH", stream, first + k) + pcm[k * 640:(k + 1) * 640]))
        time.sleep(0.0005)


def _end(link, stream: int, samples: int, reason: int = 0) -> None:  # type: ignore[no-untyped-def]
    link._dispatch(Frame(FrameType.AUDIO_END, 1, 3, struct.pack("<IBBHI", stream, reason, 0, 0, samples)))


def _until(pred, t: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    end = time.time() + t
    while time.time() < end and not pred():
        time.sleep(0.02)
    assert pred()


def test_wake_word_then_meeting_turns_the_stream_into_a_recording(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    voice, link, _ = _rig(manager, tmp_path, PhasedSTT("Meeting.", "Meeting. Hello everyone."))
    head = _speech(0.7, 1.0)  # "Meeting." then a pause
    _send(link, 21, head)
    _until(lambda: voice.meetings.owns(21))
    snap = manager.snapshot()
    assert (snap["voice_stream"], snap["voice_activity"]) == (21, "MEETING")  # PIP switches to its meeting screen
    _send(link, 21, _speech(2.0), first=len(head) // 640, start=False)
    _end(link, 21, 0)
    assert voice.meetings.wait_idle(30)
    time.sleep(0.05)
    m = voice.meetings.repo.list()[0]
    assert m["status"] == "READY" and m["duration_s"] == pytest.approx(3.7, abs=0.05)  # nothing heard was lost
    assert not voice.streams and manager.active_task() is None  # not treated as a brain dump
    assert "voice_stream" not in manager.snapshot()


def test_wake_word_then_alarms_plans_with_the_alarms_activity(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    voice, link, _events = _rig(manager, tmp_path, PhasedSTT("Alarms, wake me at", "Alarms, wake me at 7 tomorrow."))
    seen: list[str] = []
    orig = voice.process_text
    voice.process_text = lambda text, key, **kw: (seen.append(f"{kw.get('activity')}|{text}"), orig(text, key, **kw))[1]  # type: ignore[method-assign]
    _send(link, 22, _speech(2.0))
    _until(lambda: voice.activity.get(22) == "ALARMS")
    assert manager.snapshot()["voice_activity"] == "ALARMS"
    voice.stt.final = True  # type: ignore[attr-defined]
    _end(link, 22, 0)
    _until(lambda: bool(seen))
    assert seen == ["ALARMS|wake me at 7 tomorrow."]  # the name is not part of the message
    assert not voice.meetings.repo.list()


def test_talking_without_a_name_is_a_brain_dump(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    voice, link, _ = _rig(manager, tmp_path, PhasedSTT("Finish the Q3 report now please", "Finish the Q3 report now please."))
    _send(link, 23, _speech(2.0))
    _until(lambda: voice.activity.get(23) == "BRAIN_DUMP")
    voice.stt.final = True  # type: ignore[attr-defined]
    _end(link, 23, 0)
    _until(lambda: manager.active_task() is not None)
    assert "Q3 report" in manager.active_task()["title"]


def test_silence_after_the_wake_word_cancels_without_transcribing(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    stt = PhasedSTT("", "")
    _voice, link, events = _rig(manager, tmp_path, stt)
    _send(link, 24, bytes(3 * 32000))
    calls = stt.calls
    _end(link, 24, 48000, reason=CANCELLED)
    time.sleep(0.2)
    assert stt.calls == calls and manager.ui_state() == "IDLE_READY"
    assert any(k == "voice_session_updated" and p["status"] == "CANCELLED" for k, p in events)
