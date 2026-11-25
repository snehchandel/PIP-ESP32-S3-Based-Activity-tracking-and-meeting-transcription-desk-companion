"""Plans are repaired instead of rejected over step lengths; "starting in 10 minutes" becomes a start time with a
nudge; reminders nudge when due; the user's own words reach Whisper and Kimi."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from service.alarms.nudges import NudgeScheduler
from service.config import Settings
from service.main import create_app
from service.planner.schema import ActiveTask, PlannerOutputV1, Step


def test_short_steps_are_repaired_not_rejected() -> None:
    # what Kimi returned for "work in the next 10 minutes on the CASL metrics": 4-minute steps
    t = ActiveTask(title="Send CASL consent metrics to Priya", steps=[
        Step(title="Open the CST database dashboard", duration_min=2, is_starter=False),
        Step(title="Pull the CASL consent metrics", duration_min=4),
        Step(title="Email the numbers to Priya", duration_min=40, is_starter=True)])
    assert [(s.duration_min, s.is_starter) for s in t.steps] == [(2, True), (5, False), (25, False)]
    with pytest.raises(ValueError):  # structure is still strict
        ActiveTask(title="X", steps=[Step(title="Open doc", duration_min=2, is_starter=True)])


def _plan(start_local: str | None) -> PlannerOutputV1:
    return PlannerOutputV1.model_validate({"intent": "CREATE_TASK", "active_task": {
        "title": "Send CASL consent metrics to Priya", "short_title": "CASL metrics", "start_local": start_local,
        "steps": [{"title": "Open the CST database dashboard", "duration_min": 2, "is_starter": True},
                  {"title": "Pull the CASL consent metrics", "duration_min": 10},
                  {"title": "Email the numbers to Priya", "duration_min": 5}]}})


def test_start_time_goes_on_the_calendar_and_nudges(manager) -> None:  # type: ignore[no-untyped-def]
    start = datetime.now(manager.tz).replace(second=0, microsecond=0) + timedelta(minutes=10)
    tid = manager.commit_plan(_plan(start.strftime("%Y-%m-%dT%H:%M")), "casl")["task_id"]
    task = manager.tasks.get_task(tid)
    assert task["start_hhmm"] == start.strftime("%H:%M") and task["target_date"] == start.date().isoformat()
    assert manager.active_task()["id"] == tid  # ready on PIP; the timer waits for KEY
    n = NudgeScheduler(manager)
    assert n.check(start.astimezone(UTC) - timedelta(minutes=1)) == []
    said = n.check(start.astimezone(UTC) + timedelta(seconds=20))
    assert said == ["Time to start: Send CASL consent metrics to Priya. Press KEY when you're ready."]
    assert manager.snapshot()["toast"] == "Time to start: CASL metrics"
    assert n.check(start.astimezone(UTC) + timedelta(seconds=40)) == []  # once


def test_reminders_nudge_when_due_and_old_ones_stay_quiet(manager) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 11, 25, 17, 0, tzinfo=UTC)
    manager.tasks.add_reminder("Automation analyst JD meeting", "2026-11-25T17:00:00Z", "America/Toronto")
    manager.tasks.add_reminder("Long gone", "2026-11-25T15:00:00Z", "America/Toronto")
    n = NudgeScheduler(manager)
    assert n.check(now + timedelta(seconds=5)) == ["Reminder: Automation analyst JD meeting."]
    assert n.check(now + timedelta(seconds=65)) == []


def test_vocabulary_reaches_whisper_and_kimi(tmp_path) -> None:  # type: ignore[no-untyped-def]
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"),
                 moonshot_api_key="sk-test-key-123456", moonshot_base_url="http://127.0.0.1:9/v1")
    with TestClient(create_app(s)) as c:
        r = c.put("/api/v1/settings/vocabulary", json={"words": ["CASL", " CST ", "Priya", "casl", ""]})
        assert r.json()["words"] == ["CASL", "CST", "Priya"]
        assert c.get("/api/v1/settings/vocabulary").json()["words"] == ["CASL", "CST", "Priya"]
        svcs = c.app.state.services  # type: ignore[attr-defined]
        assert svcs.stt.hotwords() == "CASL, CST, Priya" and svcs.meetings.stt.vocabulary == ["CASL", "CST", "Priya"]
        svcs._model_cache = ((hash("sk-test-key-123456"), ""), "kimi-k3")  # no /models call
        assert svcs.planner().vocabulary == ["CASL", "CST", "Priya"]
