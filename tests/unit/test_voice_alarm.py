"""Spoken wake-up alarms: confirmation, voice/script selection, and the ring sequence
(speech -> 1 minute of chimes) stopping the moment the alarm is dismissed."""
from __future__ import annotations

import asyncio
import struct
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from service.alarms import audio as alarm_audio
from service.alarms.audio import AlarmAudio
from service.config import Settings
from service.main import create_app
from service.planner.schema import PlannerOutputV1, ScheduledItem
from service.protocol import FrameType
from service.state.reconcile import ack_text

SCRIPT = " ".join(["Rise and shine, you are doing great."] * 10) + " Time to get up."


def _plan(**item: object) -> PlannerOutputV1:
    base = {"kind": "ALARM", "title": "Gym wake-up", "due_local": "2026-11-25T05:00"}
    return PlannerOutputV1.model_validate({"intent": "ADD_ALARM", "scheduled": [{**base, **item}]})


def test_script_is_tidied_and_short_ones_flagged() -> None:
    it = ScheduledItem(kind="ALARM", title="Gym", use_voice=True, script='  "Wake up."  ')
    assert it.script == "Wake up." and it.needs_script
    assert not ScheduledItem(kind="ALARM", title="Gym", use_voice=True, script=SCRIPT).needs_script
    assert ScheduledItem(kind="ALARM", title="Gym", script="x" * 5000).script == "x" * 1200


def test_ack_text_is_short_ascii_for_the_device() -> None:
    a = ack_text([{"kind": "ALARM", "due_local": "2026-11-25T05:00", "use_voice": True}])
    assert a["short"] == "Alarm set: Wed 05:00"
    assert a["short"].isascii()
    assert a["spoken"] == "Done. Alarm set for Wednesday at 5 AM with a voice wake-up."


def test_voice_alarm_commit_uses_female_voice_and_confirms(manager) -> None:  # type: ignore[no-untyped-def]
    events: list[tuple[str, dict]] = []  # type: ignore[type-arg]
    manager.subscribe(lambda k, p: events.append((k, p)))
    manager.voice_for_style = lambda style: {"female": "en_GB-jenny_dioco-medium"}.get(style)
    out = manager.commit_plan(_plan(use_voice=True, voice_style="female", script=SCRIPT))
    a = manager.alarms.get(out["scheduled_ids"][0])
    assert a["audio_mode"] == "TTS" and a["voice"] == "en_GB-jenny_dioco-medium" and a["tts_script"] == SCRIPT
    snap = manager.snapshot()
    assert snap["toast"] == "Alarm set: Wed 05:00" and snap["toast_id"] > 0
    assert events[-1][0] == "items_scheduled" and events[-1][1]["ack"]["short"] == "Alarm set: Wed 05:00"


def test_voice_alarm_without_script_gets_the_builtin_one(manager) -> None:  # type: ignore[no-untyped-def]
    out = manager.commit_plan(_plan(use_voice=True))
    a = manager.alarms.get(out["scheduled_ids"][0])
    assert a["audio_mode"] == "TTS" and "Gym wake-up" in a["tts_script"] and len(a["tts_script"].split()) >= 60


class _Link:
    linked = True

    def __init__(self) -> None:
        self.frames: list[tuple[int, bytes]] = []
        self.chimes = 0

    def send(self, t: int, payload: bytes, ack: bool = False) -> bool:
        self.frames.append((t, payload))
        return True

    def play_chime(self, cid: int) -> None:
        self.chimes += 1


class _Tts:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def synthesize_pcm(self, text: str, voice: str | None = None, scale: float | None = None) -> np.ndarray:
        self.calls.append((text, voice))
        return np.zeros(32000, dtype=np.int16)  # 2 s (longer than the 0.5 s pre-fill)


@pytest.fixture()
def fast(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(alarm_audio, "RING_LEAD_S", 0.0)
    monkeypatch.setattr(alarm_audio, "AFTER_SPEECH_S", 0.0)
    monkeypatch.setattr(alarm_audio, "CHIME_PERIOD_S", 0.05)
    monkeypatch.setattr(alarm_audio, "CHIME_FOR_S", 0.3)


def _setup(manager, tmp_path):  # type: ignore[no-untyped-def]
    aid = manager.alarms.create(title="Gym wake-up", local_hhmm="05:00", fire_utc="2026-11-25T10:00:00Z", timezone="America/Toronto",
                                audio_mode="TTS", tts_script=SCRIPT, voice="en_GB-jenny_dioco-medium")
    link, tts = _Link(), _Tts()
    svc = SimpleNamespace(manager=manager, link=link, tts=tts, db=manager.db)
    return aid, link, tts, AlarmAudio(svc, tmp_path)  # type: ignore[arg-type]


def test_ring_speaks_script_then_chimes_for_a_minute(manager, tmp_path, fast) -> None:  # type: ignore[no-untyped-def]
    aid, link, tts, aa = _setup(manager, tmp_path)
    aa.render(manager.alarms.get(aid))  # pre-rendered at creation time...
    assert tts.calls == [(SCRIPT, "en_GB-jenny_dioco-medium")]
    manager.ring(manager.alarms.get(aid))
    asyncio.run(aa.ring_sequence(aid))
    assert len(tts.calls) == 1  # ...so ringing reuses the cached audio
    types = [t for t, _ in link.frames]
    assert types[0] == FrameType.AUDIO_START_OUT and types[-1] == FrameType.AUDIO_END_OUT
    assert link.frames[-1][1][4] == 0  # finished normally, not aborted
    assert 4 <= link.chimes <= 8  # chimes after the speech until CHIME_FOR_S elapsed
    assert manager.ringing is not None  # the screen stays until dismissed


def test_dismiss_during_speech_stops_voice_and_chimes(manager, tmp_path, fast) -> None:  # type: ignore[no-untyped-def]
    aid, link, _tts, aa = _setup(manager, tmp_path)
    manager.ring(manager.alarms.get(aid))

    async def go() -> None:
        task = asyncio.create_task(aa.ring_sequence(aid))
        await asyncio.sleep(0.15)  # mid-speech
        manager.ack_alarm(snooze=False)
        await task

    asyncio.run(go())
    end = link.frames[-1]
    assert end[0] == FrameType.AUDIO_END_OUT and struct.unpack("<IBBBB", end[1])[1] == 1  # abort flag
    assert link.chimes == 0


def test_alarm_api_voice_and_script(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from tests.support.fake_kimi import FakeKimi
    kimi = FakeKimi()
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"),
                 moonshot_api_key="sk-test-fake-0000", moonshot_base_url=kimi.base_url)
    try:
        with TestClient(create_app(s)) as c:
            body = {"title": "Gym", "local_hhmm": "05:00", "audio_mode": "TTS"}
            assert c.post("/api/v1/alarms", json=body).status_code == 422  # no script
            r = c.post("/api/v1/alarms/script", json={"title": "Gym"}).json()
            assert r["words"] >= 40 and r["script"].endswith("Time to get up.")
            bad = c.post("/api/v1/alarms", json={**body, "voice": "no-such-voice", "tts_script": r["script"]})
            assert bad.status_code == 404
            a = c.post("/api/v1/alarms", json={**body, "tts_script": r["script"]}).json()
            assert a["audio_mode"] == "TTS" and a["tts_script"] == r["script"]
            kimi.down = True
            assert c.post("/api/v1/alarms/script", json={"title": "Gym"}).status_code == 503
    finally:
        kimi.close()
