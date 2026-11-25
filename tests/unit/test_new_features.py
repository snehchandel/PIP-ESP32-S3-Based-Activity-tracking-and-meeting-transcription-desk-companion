"""Test-alarm auto-dismiss, timed calendar items, dashboard key handling, Piper resampling."""
from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
from fastapi.testclient import TestClient
from service.alarms.schedule import fmt_utc
from service.alarms.scheduler import AlarmScheduler
from service.calendar.agenda import day_items
from service.config import Settings
from service.main import create_app
from service.speech.tts import resample
from service.state.reconcile import TEST_RING_S

from ..conftest import TZ


def _alarm(manager):  # type: ignore[no-untyped-def]
    return manager.alarms.create(title="Gym", schedule_kind="ONCE", local_hhmm="18:00", timezone="America/Toronto",
                                 fire_utc=fmt_utc(datetime(2030, 1, 1, tzinfo=UTC)))


def test_test_ring_auto_dismisses_after_30s_and_keeps_alarm_armed(manager) -> None:  # type: ignore[no-untyped-def]
    aid = _alarm(manager)
    assert AlarmScheduler(manager).test(aid)
    assert manager.ui_state() == "ALARM_RINGING" and manager.snapshot()["alarm_ringing"] is True
    manager._clock["t"] += TEST_RING_S - 1
    assert manager.tick() is False and manager.ringing is not None
    manager._clock["t"] += 1
    assert manager.tick() is True
    assert manager.ringing is None and manager.snapshot()["alarm_ringing"] is False
    a = manager.alarms.get(aid)
    assert a["enabled"] == 1 and a["ack_state"] == "IDLE"  # a test never consumes the real alarm


def test_dismissing_a_test_ring_does_not_disable_the_alarm(manager) -> None:  # type: ignore[no-untyped-def]
    aid = _alarm(manager)
    AlarmScheduler(manager).test(aid)
    manager.ack_alarm(snooze=False)
    assert manager.alarms.get(aid)["enabled"] == 1


def test_real_ring_does_not_auto_dismiss(manager) -> None:  # type: ignore[no-untyped-def]
    aid = _alarm(manager)
    manager.ring(manager.alarms.get(aid))
    manager._clock["t"] += 600
    manager.tick()
    assert manager.ringing is not None


def test_timed_tasks_and_recurring_alarms_on_calendar(manager) -> None:  # type: ignore[no-untyped-def]
    steps = [{"title": "Open doc", "duration_min": 2, "is_starter": True}, {"title": "Write", "duration_min": 20},
             {"title": "Edit", "duration_min": 10}]
    tid = manager.tasks.create_task("Q3 report", steps, "2026-11-23", "America/Toronto", start_hhmm="09:30")
    manager.tasks.create_task("Anytime thing", steps, "2026-11-23", "America/Toronto")
    manager.alarms.create(title="Standup", schedule_kind="RECURRING", rrule_days="MO,WE", local_hhmm="10:00",
                          timezone="America/Toronto")
    items = day_items(manager.tasks.list_tasks(), [], manager.alarms.list(), date(2026, 11, 23), TZ)  # Monday
    by = {i["title"]: i for i in items}
    assert by["Q3 report"]["hhmm"] == "09:30" and by["Q3 report"]["duration_min"] == 32
    assert by["Anytime thing"]["hhmm"] == ""
    assert by["Standup"]["hhmm"] == "10:00" and by["Standup"]["recurring"]
    tuesday = day_items(manager.tasks.list_tasks(), [], manager.alarms.list(), date(2026, 11, 24), TZ)
    assert "Standup" not in {i["title"] for i in tuesday}
    manager.tasks.update_task(tid, start_hhmm="")
    assert manager.tasks.get_task(tid)["start_hhmm"] is None


def test_planner_timed_task_gets_start_time(manager, now) -> None:  # type: ignore[no-untyped-def]
    from service.planner.local_rule import LocalRulePlanner
    manager.commit_plan(LocalRulePlanner().plan("gym tomorrow at 7:30am", now), "x")
    t = [t for t in manager.tasks.list_tasks() if t["title"] == "Gym"][0]
    assert t["start_hhmm"] == "07:30" and t["target_date"] == "2026-11-24"


def _client(tmp_path, **kw):  # type: ignore[no-untyped-def]
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"), **kw)
    return TestClient(create_app(s))


def test_api_key_is_never_returned_in_full(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path, moonshot_api_key="sk-testsecretvalue1234") as c:
        s = c.get("/api/v1/settings").json()
        assert s["api_key"] == {"configured": True, "source": "env", "hint": "…1234", "editable": False}
        assert "testsecret" not in c.get("/api/v1/settings").text
        assert c.put("/api/v1/settings/api-key", json={"key": "sk-anotherkey99999"}).status_code == 409
        assert c.get("/api/v1/health").json()["planner_mode"] == "KIMI"


def test_no_key_means_ai_has_left(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as c:
        s = c.get("/api/v1/settings").json()
        assert s["api_key"]["configured"] is False and s["planner_mode"] == "AI_NOT_CONFIGURED"
        assert c.post("/api/v1/settings/api-key/test", json={}).json()["ok"] is False
        r = c.post("/api/v1/tasks/plan", json={"text": "Finish the report", "auto_commit": True})
        assert r.status_code == 503 and "AI has left the device" in r.json()["detail"]
        st = c.get("/api/v1/state").json()
        assert st["ui_state"] == "ERROR_RECOVERABLE" and st["error"]["title"] == "AI has left the device"
        assert c.post("/api/v1/error/dismiss").json()["dismissed"] is True
        assert c.get("/api/v1/state").json()["ui_state"] == "IDLE_READY"


def test_stuck_thinking_becomes_logged_error(manager) -> None:  # type: ignore[no-untyped-def]
    manager.overlay = "THINKING"
    assert manager.check_stuck() is False  # first sighting starts the clock
    manager._clock["t"] += manager.STUCK_LIMITS_S["THINKING"] + 1
    assert manager.check_stuck() is True
    assert manager.ui_state() == "ERROR_RECOVERABLE" and manager.overlay is None
    rows = manager.db.query("SELECT level, category, message FROM event_log WHERE level='ERROR'")
    assert any(r["category"] == "watchdog" and "THINKING" in r["message"] for r in rows)


def test_weather_icon_mapping() -> None:
    from service.weather import default_city, icon_for
    assert [icon_for(c) for c in (0, 2, 3, 45, 53, 61, 73, 95)] == [0, 6, 1, 5, 9, 2, 3, 4]
    assert [icon_for(c, is_day=False) for c in (0, 1, 2, 3)] == [7, 7, 8, 1]  # night sky: moon
    assert default_city("America/New_York") == "New York"


def test_task_api_accepts_and_clears_time(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as c:
        t = c.post("/api/v1/tasks", json={"title": "Dentist prep", "target_date": "2026-11-25", "start_hhmm": "14:15"}).json()
        assert t["start_hhmm"] == "14:15"
        assert c.post("/api/v1/tasks", json={"title": "x", "target_date": "2026-11-25", "start_hhmm": "25:00"}).status_code == 422
        assert c.patch(f"/api/v1/tasks/{t['id']}", json={"start_hhmm": ""}).json()["start_hhmm"] is None


def test_resample_to_device_rate() -> None:
    pcm = (np.sin(np.linspace(0, 200, 22050)) * 10000).astype(np.int16)  # 1 s at 22.05 kHz
    out = resample(pcm, 22050)
    assert out.dtype == np.int16 and abs(out.size - 16000) <= 1
    assert resample(out, 16000) is not None and resample(out, 16000).size == out.size
