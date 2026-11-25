"""Meeting recordings (device stream -> WAV on disk -> transcript with speakers), remembered voices, review API
and exports; parking the active task; Kimi-planned steps for promoted notes; resizable calendar blocks."""
from __future__ import annotations

import json
import struct
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from service.config import Settings
from service.device.link import DeviceLink
from service.main import create_app
from service.meetings import diarize
from service.meetings.service import MeetingService, finalize_wav, wav_header
from service.planner.schema import PlannerOutputV1, Step
from service.protocol import Frame, FrameType
from service.speech.pipeline import VoicePipeline

from tests.support.fake_kimi import FakeKimi
from tests.support.meeting_audio import (
    ScriptedSegmentsSTT,
    piper_available,
    synth_meeting,
)

JENNY, RYAN, HFC, LESSAC = ("en_GB-jenny_dioco-medium", "en_US-ryan-medium", "en_US-hfc_female-medium",
                            "en_US-lessac-medium")
needs_piper = pytest.mark.skipif(not piper_available(JENNY, RYAN, HFC), reason="Piper voices not installed")


def _service(manager, tmp_path: Path, segments=None):  # type: ignore[no-untyped-def]
    events: list[tuple[str, dict]] = []  # type: ignore[type-arg]
    svc = MeetingService(manager, tmp_path, "small.en", lambda k, p: events.append((k, p)),
                         stt=ScriptedSegmentsSTT(segments or [(0.0, 0.9, "Hello there.")]))  # type: ignore[arg-type]
    return svc, events


def _audio_frames(stream: int, pcm: bytes, first_seq: int = 0, skip: range | None = None) -> list[Frame]:
    start = struct.pack("<IHBBHH", stream, 16000, 1, 16, 0, 4)  # activity 4 = MEETING, max_sec 0 = no limit
    out = [Frame(FrameType.AUDIO_START, 1, 1, start)]
    for k in range(len(pcm) // 640):
        if skip is not None and k in skip:
            continue  # lost while the link was down
        out.append(Frame(FrameType.AUDIO_DATA, 0, 2, struct.pack("<IH", stream, (first_seq + k) & 0xFFFF)
                         + pcm[k * 640:(k + 1) * 640]))
    out.append(Frame(FrameType.AUDIO_END, 1, 3, struct.pack("<IBBHI", stream, 0, 0, 0, len(pcm) // 2)))
    return out


def _wait(svc: MeetingService) -> None:
    assert svc.wait_idle(60)
    time.sleep(0.05)


# ---- recording --------------------------------------------------------------------------------------
def test_meeting_stream_is_recorded_to_wav_and_gaps_are_filled(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc, events = _service(manager, tmp_path)
    voice = VoicePipeline(manager, None, lambda: None, lambda k, p: None)  # type: ignore[arg-type]
    voice.meetings = svc
    link = DeviceLink(manager, None, voice, lambda k, p: None)
    pcm = (np.sin(np.arange(16000 * 3) / 7.0) * 3000).astype("<i2").tobytes()  # 3 s, 150 chunks
    # 20 chunks (0.4 s) lost to a link drop; the seq counter wraps past 65535 mid-stream
    for f in _audio_frames(9, pcm, first_seq=65500, skip=range(60, 80)):
        assert link._dispatch(f) == 0
    _wait(svc)
    m = svc.repo.list()[0]
    assert m["status"] == "READY" and m["source"] == "DEVICE"
    assert m["gaps_s"] == pytest.approx(0.4)
    with wave.open(m["audio_path"]) as w:  # a valid WAV whose timeline includes the lost audio as silence
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert w.getnframes() == 150 * 320
    assert m["duration_s"] == pytest.approx(3.0)
    assert any(k == "meeting_updated" and p["status"] == "READY" for k, p in events)
    assert svc.repo.segments(m["id"])[0]["text"] == "Hello there."
    assert not voice.streams  # nothing went to the brain-dump path


def test_meeting_pauses_a_running_focus_timer(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    plan = PlannerOutputV1.model_validate({"intent": "CREATE_TASK", "active_task": {"title": "Q3 report", "steps": [
        {"title": "Open the Q3 doc", "duration_min": 2, "is_starter": True},
        {"title": "Write the summary", "duration_min": 20}, {"title": "Send it to Ana", "duration_min": 5}]}})
    manager.commit_plan(plan, "q3")
    manager.timer_start()
    svc, _ = _service(manager, tmp_path)
    svc.start(3)
    assert manager.timer.state == "PAUSED"
    svc.end(3)
    _wait(svc)


def test_interrupted_recording_is_recovered_at_startup(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc, _ = _service(manager, tmp_path)
    mid = svc.start(5)
    svc.data(5, bytes(640 * 100), 0)
    svc._rec[5].f.flush()  # the host "crashes" here: header still says 0 bytes
    svc._rec[5].f.close()
    svc._rec.clear()
    fresh, _ = _service(manager, tmp_path)
    fresh.recover()
    _wait(fresh)
    m = fresh.repo.get(mid)
    assert m is not None and m["status"] == "READY" and m["duration_s"] == pytest.approx(2.0)
    assert finalize_wav(Path(m["audio_path"])) == pytest.approx(2.0)


def test_silent_device_closes_the_meeting(manager, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    svc, _ = _service(manager, tmp_path)
    mid = svc.start(6)
    svc.data(6, bytes(640 * 50), 0)
    from service.meetings import service as msvc
    monkeypatch.setattr(msvc, "STALE_RECORDING_S", -1.0)
    svc.tick()
    _wait(svc)
    assert svc.repo.get(mid)["status"] == "READY"  # type: ignore[index]


def test_meeting_is_named_after_the_calendar_item(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    manager.tasks.create_task("Design review with Ana", [{"title": "Join the call", "duration_min": 30}],
                              "2026-11-24", "America/Toronto", start_hhmm="14:30")
    svc, _ = _service(manager, tmp_path)
    start = datetime(2026, 11, 24, 19, 33, tzinfo=UTC)  # 14:33 in Toronto
    assert svc.default_title(start) == "Design review with Ana"
    assert svc.default_title(datetime(2026, 11, 24, 23, 0, tzinfo=UTC)).startswith("Meeting · Tue Nov 24, 18:00")


# ---- speakers ------------------------------------------------------------------------------------------
def _features(pcm: bytes, truth):  # type: ignore[no-untyped-def]
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return [diarize.voice_features(audio[int(a * 16000):int(b * 16000)]) for a, b, _, _ in truth]


def _accuracy(labels: list[int], truth) -> float:  # type: ignore[no-untyped-def]
    from itertools import permutations
    t = [x[3] for x in truth]
    k = max(max(labels), max(t)) + 1
    return max(sum(p[a] == b for a, b in zip(labels, t, strict=True)) for p in permutations(range(k))) / len(t)


@needs_piper
@pytest.mark.parametrize("voices", [[LESSAC], [JENNY, RYAN], [JENNY, RYAN, HFC]])
def test_voices_are_told_apart(voices) -> None:  # type: ignore[no-untyped-def]
    pcm, truth = synth_meeting(voices, seed=len(voices))
    d = diarize.diarize(_features(pcm, truth), [b - a for a, b, _, _ in truth])
    assert max(d.labels) + 1 == len(voices)
    assert _accuracy(d.labels, truth) >= 0.9
    assert d.labels[0] == 0  # speakers are numbered by first appearance


@needs_piper
def test_forcing_the_speaker_count() -> None:
    pcm, truth = synth_meeting([JENNY, RYAN], seed=3)
    d = diarize.diarize(_features(pcm, truth), [b - a for a, b, _, _ in truth], num_speakers=3)
    assert max(d.labels) + 1 == 3


@needs_piper
def test_named_voice_is_recognised_in_the_next_meeting(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    pcm, truth = synth_meeting([JENNY, RYAN], seed=4)
    segs = [(a, b, text) for a, b, text, _ in truth]
    svc, _ = _service(manager, tmp_path, segs)
    mid = svc.import_audio(_wav(tmp_path / "a.wav", pcm), "Monday sync")
    _wait(svc)
    m = svc.repo.get(mid)
    assert [s["name"] for s in m["speakers"]] == ["Speaker 01", "Speaker 02"]  # type: ignore[index]
    first = svc.repo.segments(mid)[0]
    svc.rename_speaker(mid, first["speaker_key"], "Priya", remember=True)
    other = "S2" if first["speaker_key"] == "S1" else "S1"
    svc.rename_speaker(mid, other, "Ryan", remember=True)
    assert {p["name"] for p in svc.repo.profiles()} == {"Priya", "Ryan"}
    # a new meeting, other lines, Ryan speaks first this time
    pcm2, truth2 = synth_meeting([RYAN, JENNY], lines=[t for _, _, t, _ in truth][::-1], seed=5)
    svc.stt = ScriptedSegmentsSTT([(a, b, text) for a, b, text, _ in truth2])  # type: ignore[assignment]
    mid2 = svc.import_audio(_wav(tmp_path / "b.wav", pcm2), "Tuesday sync")
    _wait(svc)
    sp = svc.repo.get(mid2)["speakers"]  # type: ignore[index]
    assert [(s["name"], s["auto"]) for s in sp] == [("Ryan", True), ("Priya", True)]
    lines = svc.repo.segments(mid2)
    names = {s["key"]: s["name"] for s in sp}
    right = sum(names[s["speaker_key"]] == ("Ryan" if t[3] == 0 else "Priya") for s, t in zip(lines, truth2, strict=True))
    assert right / len(lines) >= 0.9


def _wav(path: Path, pcm: bytes) -> Path:
    path.write_bytes(wav_header(len(pcm)) + pcm)
    return path


# ---- review API + exports -----------------------------------------------------------------------------
def _client(tmp_path: Path, **kw) -> TestClient:  # type: ignore[no-untyped-def]
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"), **kw)
    return TestClient(create_app(s))


def test_meeting_review_api_and_exports(tmp_path) -> None:  # type: ignore[no-untyped-def]
    kimi = FakeKimi()
    with _client(tmp_path, moonshot_api_key="sk-test-key-123456", moonshot_base_url=kimi.base_url) as c:
        svcs = c.app.state.services  # type: ignore[attr-defined]
        rng = np.random.default_rng(0)
        pcm = (rng.normal(0, 2000, 16000 * 6)).astype("<i2").tobytes()
        svcs.meetings.stt = ScriptedSegmentsSTT([(0.0, 2.0, "Let's start."), (2.2, 4.0, "I'll send the budget."),
                                                 (4.2, 5.8, "Thanks, bye.")])
        wav = _wav(tmp_path / "in.wav", pcm)
        r = c.post("/api/v1/meetings/import?filename=in.wav&title=Budget%20chat", content=wav.read_bytes())
        assert r.status_code == 200
        mid = r.json()["id"]
        _wait(svcs.meetings)
        lst = c.get("/api/v1/meetings").json()
        assert lst["meetings"][0]["id"] == mid and lst["meetings"][0]["status"] == "READY"
        m = c.get(f"/api/v1/meetings/{mid}").json()
        assert m["title"] == "Budget chat" and len(m["segments"]) == 3 and m["duration_s"] == pytest.approx(6.0)
        # name a speaker, add one the detection missed, move a line to them, fix a word
        key = m["speakers"][0]["key"]
        assert c.put(f"/api/v1/meetings/{mid}/speakers/{key}", json={"name": "Ana", "remember": False}).status_code == 200
        new = c.post(f"/api/v1/meetings/{mid}/speakers", json={"name": "Sam"}).json()["key"]
        seg = m["segments"][1]["id"]
        assert c.patch(f"/api/v1/meetings/{mid}/segments/{seg}", json={"speaker_key": new,
                                                                        "text": "I'll send the Q3 budget."}).status_code == 200
        assert c.patch(f"/api/v1/meetings/{mid}/segments/{seg}", json={"speaker_key": "S99"}).status_code == 404
        assert c.patch(f"/api/v1/meetings/{mid}", json={"notes": "Follow up Friday"}).status_code == 200
        # exports
        md = c.get(f"/api/v1/meetings/{mid}/export?format=md")
        assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
        assert "# Budget chat" in md.text and "**Sam**" in md.text and "Q3 budget" in md.text and "Follow up Friday" in md.text
        assert md.text.startswith("---\ntype: meeting\n") and "[[Ana]]" in md.text  # an Obsidian note
        srt = c.get(f"/api/v1/meetings/{mid}/export?format=srt").text
        assert "00:00:02,200 --> 00:00:04,000" in srt and "Sam: I'll send the Q3 budget." in srt
        js = json.loads(c.get(f"/api/v1/meetings/{mid}/export?format=json").text)
        assert [s["speaker"] for s in js["segments"]] == ["Ana", "Sam", "Ana"]
        txt = c.get(f"/api/v1/meetings/{mid}/export?format=txt").text
        assert "Speakers: Ana, Sam" in txt and "[00:02] Sam: I'll send the Q3 budget." in txt
        assert c.get(f"/api/v1/meetings/{mid}/export?format=pdf").status_code == 422
        audio = c.get(f"/api/v1/meetings/{mid}/audio")
        assert audio.status_code == 200 and audio.content[:4] == b"RIFF"
        # Kimi summary -> action items into Parked tangents
        summ = c.post(f"/api/v1/meetings/{mid}/summarize?engine=kimi").json()
        assert summ["action_items"][0]["task"] == "Send the Q3 budget spreadsheet"
        assert "## Summary" in c.get(f"/api/v1/meetings/{mid}/export?format=md").text
        parked = c.post(f"/api/v1/meetings/{mid}/park-actions").json()["parked_ids"]
        assert len(parked) == 2 and len(c.get("/api/v1/state").json()["parked"]) == 2
        assert c.post(f"/api/v1/meetings/{mid}/park-actions").json()["parked_ids"] == []  # never parked twice
        # merge speakers, re-run detection with a fixed count, delete
        assert c.post(f"/api/v1/meetings/{mid}/speakers/{new}/merge", json={"into": key}).status_code == 200
        assert len(c.get(f"/api/v1/meetings/{mid}").json()["speakers"]) == 1
        assert len(c.post(f"/api/v1/meetings/{mid}/rediarize", json={"num_speakers": 2}).json()["speakers"]) == 2
        path = Path(svcs.meetings.repo.get(mid)["audio_path"])
        assert c.delete(f"/api/v1/meetings/{mid}").status_code == 200 and not path.exists()
        assert c.get(f"/api/v1/meetings/{mid}").status_code == 404
    kimi.server.shutdown()


# ---- park the task in progress ------------------------------------------------------------------------------
def _task(manager) -> str:  # type: ignore[no-untyped-def]
    plan = PlannerOutputV1.model_validate({"intent": "CREATE_TASK", "active_task": {
        "title": "Buy winter pants for my son", "short_title": "Kids' pants", "steps": [
            {"title": "Grab keys, wallet and his size", "duration_min": 2, "is_starter": True, "activity": "errand"},
            {"title": "Drive to Old Navy", "duration_min": 15, "activity": "errand"},
            {"title": "Find kids' winter pants", "duration_min": 15, "activity": "errand"}]}})
    return str(manager.commit_plan(plan, "old navy")["task_id"])


def test_park_active_task_keeps_its_steps_and_resumes(manager) -> None:  # type: ignore[no-untyped-def]
    tid = _task(manager)
    manager.complete_step()  # starter done
    manager.start_next_step()
    manager._clock["t"] += 120  # 2 minutes into "Drive to Old Navy"
    pid = manager.park_active_task()
    assert pid and manager.active_task() is None and manager.timer.state == "STOPPED"
    note = manager.tasks.get_parked(pid)
    assert note["task_id"] == tid and "Drive to Old Navy (15 min)" in note["source_text"]
    assert manager.snapshot()["toast"] == "Parked for later" and manager.snapshot()["step_id"] == ""
    assert tid not in [t["id"] for t in manager.tasks.list_tasks()]  # off the calendar while parked
    assert manager.resume_parked_task(pid) == tid
    st = manager.active_step()
    assert st["title"] == "Drive to Old Navy" and st["remaining_sec"] == 13 * 60  # carries on where it stopped
    assert manager.tasks.get_parked(pid)["status"] == "PROMOTED"


def test_boot_double_click_parks_the_task(manager) -> None:  # type: ignore[no-untyped-def]
    _task(manager)
    assert manager.apply_button(1, 2) == "park"  # BOOT, DOUBLE
    assert manager.active_task() is None and len(manager.tasks.parked()) == 1
    assert manager.apply_button(1, 2) == "ignored"


def test_step_activity_from_kimi_drives_pip(manager) -> None:  # type: ignore[no-untyped-def]
    _task(manager)
    snap = manager.snapshot()
    # "Grab keys, wallet..." has no errand keyword: the plan's own activity wins over the keyword rules
    assert snap["activity"] == "errand" and snap["next_activity"] == "errand"


def test_generic_filler_steps_are_rejected() -> None:
    with pytest.raises(ValueError, match="generic filler"):
        Step(title="Work on the first part of it", duration_min=10)
    assert Step(title="Drive to Old Navy", duration_min=15, activity="errand").activity == "errand"
    with pytest.raises(ValueError):
        Step(title="Drive to Old Navy", duration_min=15, activity="flying")  # type: ignore[arg-type]


def test_park_and_promote_api(tmp_path) -> None:  # type: ignore[no-untyped-def]
    kimi = FakeKimi()
    with _client(tmp_path, moonshot_api_key="sk-test-key-123456", moonshot_base_url=kimi.base_url) as c:
        m = c.app.state.services.manager  # type: ignore[attr-defined]
        tid = _task(m)
        assert c.post(f"/api/v1/tasks/{tid}/park").status_code == 200
        assert c.post(f"/api/v1/tasks/{tid}/park").status_code == 404  # already parked
        st = c.get("/api/v1/state").json()
        assert st["active_task"] is None and st["parked"][0]["task_id"] == tid
        r = c.post(f"/api/v1/parked/{st['parked'][0]['id']}/promote").json()
        assert r == {"task_id": tid, "resumed": True}
        # a parked *thought* (no steps yet) is broken into steps by Kimi, not by generic templates
        pid = m.tasks.park("Write the grant report", "I need to write the grant report for the city")
        calls = kimi.calls
        r = c.post(f"/api/v1/parked/{pid}/promote")
        assert r.status_code == 200 and kimi.calls > calls
        task = m.tasks.get_task(r.json()["task_id"])
        assert task is not None and 3 <= len(task["steps"]) <= 6
        assert c.get("/api/v1/state").json()["ui_state"] != "THINKING"
        # Kimi down: the note stays parked and the app gets a clear error
        pid2 = m.tasks.park("Plan the trip", "plan the camping trip")
        kimi.down = True
        r = c.post(f"/api/v1/parked/{pid2}/promote")
        assert r.status_code == 502 and "Kimi" in r.json()["detail"]
        assert m.tasks.get_parked(pid2)["status"] == "PARKED"
    kimi.server.shutdown()


def test_calendar_blocks_can_be_resized(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as c:
        t = c.post("/api/v1/tasks", json={"title": "Dentist", "target_date": "2026-11-26", "start_hhmm": "10:00",
                                          "steps": [{"title": "Drive to the dentist", "duration_min": 20}]}).json()
        day = c.get("/api/v1/calendar?start=2026-11-26&days=1").json()[0]
        assert day["items"][0]["duration_min"] == 20
        r = c.patch(f"/api/v1/tasks/{t['id']}", json={"start_hhmm": "11:30", "target_date": "2026-11-27",
                                                      "block_min": 90})
        assert r.status_code == 200
        day = c.get("/api/v1/calendar?start=2026-11-27&days=1").json()[0]
        assert (day["items"][0]["hhmm"], day["items"][0]["duration_min"]) == ("11:30", 90)
        c.patch(f"/api/v1/tasks/{t['id']}", json={"block_min": 0})  # back to the steps' length
        assert c.get("/api/v1/calendar?start=2026-11-27&days=1").json()[0]["items"][0]["duration_min"] == 20
