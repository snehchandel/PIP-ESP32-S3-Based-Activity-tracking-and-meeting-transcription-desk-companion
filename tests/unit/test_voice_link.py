"""Device voice path: AUDIO_START/AUDIO_DATA/AUDIO_END frames -> STT -> planner -> committed plan.

The speech engine is a test double here (real faster-whisper is exercised manually on hardware)."""
from __future__ import annotations

import struct
import time

from service.device.link import DeviceLink
from service.protocol import Frame, FrameType
from service.speech.pipeline import VoicePipeline


class ScriptedSTT:  # test-only double; production uses service.speech.stt.SpeechToText
    status = "TEST"

    def __init__(self, text: str) -> None:
        self.text = text
        self.got = b""

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        self.got = pcm
        return self.text


def _frames(stream: int, chunks: int) -> list[Frame]:
    out = [Frame(FrameType.AUDIO_START, 1, 1, struct.pack("<IHBBHH", stream, 16000, 1, 16, 60, 0))]
    for i in range(chunks):
        out.append(Frame(FrameType.AUDIO_DATA, 0, 2 + i, struct.pack("<IH", stream, i) + bytes(640)))
    out.append(Frame(FrameType.AUDIO_END, 1, 99, struct.pack("<IBBHI", stream, 0, 0, 0, chunks * 320)))
    return out


def _link(manager, stt):  # type: ignore[no-untyped-def]
    from service.planner.local_rule import LocalRulePlanner
    events: list[tuple[str, dict]] = []  # type: ignore[type-arg]
    voice = VoicePipeline(manager, stt, lambda: LocalRulePlanner(), lambda k, p: events.append((k, p)))
    return DeviceLink(manager, None, voice, lambda k, p: events.append((k, p))), events


def test_voice_frames_become_a_committed_plan(manager) -> None:  # type: ignore[no-untyped-def]
    stt = ScriptedSTT("Finish Q3 report, also remind me to call dentist")
    link, events = _link(manager, stt)
    for f in _frames(7, 50):  # 1 s of audio
        assert link._dispatch(f) == 0
    deadline = time.time() + 5
    while time.time() < deadline and not manager.active_task():
        time.sleep(0.02)
    assert len(stt.got) == 50 * 640
    task = manager.active_task()
    assert task is not None and "Q3 report" in task["title"]
    assert [p["title"] for p in manager.tasks.parked()] == ["Call dentist"]
    assert any(k == "voice_session_updated" and p["status"] == "DONE" for k, p in events)
    assert manager.device.voice_sessions()[0]["status"] == "COMMITTED"


def test_empty_transcript_is_calm_noop(manager) -> None:  # type: ignore[no-untyped-def]
    link, events = _link(manager, ScriptedSTT(""))
    for f in _frames(8, 10):
        link._dispatch(f)
    deadline = time.time() + 3
    while time.time() < deadline and not any(p.get("status") == "EMPTY" for _, p in events):
        time.sleep(0.02)
    assert any(p.get("status") == "EMPTY" for _, p in events)
    assert manager.active_task() is None and manager.ui_state() == "IDLE_READY"


def test_unknown_frame_type_is_rejected(manager) -> None:  # type: ignore[no-untyped-def]
    link, _ = _link(manager, ScriptedSTT(""))
    assert link._dispatch(Frame(0x99, 0, 1, b"")) == 5  # UNKNOWN_TYPE
