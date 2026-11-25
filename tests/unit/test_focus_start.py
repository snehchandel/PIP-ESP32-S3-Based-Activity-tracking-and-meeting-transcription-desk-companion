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


def test_start_nudge_waits_while_focusing_on_another_task(manager) -> None:  # type: ignore[no-untyped-def]
    start = datetime.now(manager.tz).replace(second=0, microsecond=0) + timedelta(minutes=10)
    casl = manager.commit_plan(_plan(start.strftime("%Y-%m-%dT%H:%M")), "casl")["task_id"]
    other = PlannerOutputV1.model_validate({"intent": "CREATE_TASK", "active_task": {
        "title": "Ask Priya about the rep ID", "short_title": "Rep ID", "steps": [
            {"title": "Open the thread with the URL", "duration_min": 2, "is_starter": True},
            {"title": "Draft the two questions", "duration_min": 10}, {"title": "Send them to Priya", "duration_min": 5}]}})
    rep = manager.commit_plan(other, "rep")["task_id"]
    manager.activate_task(rep)  # the user switched to the rep ID task...
    manager.timer_start()       # ...and is mid-step when the CASL start time comes
    n = NudgeScheduler(manager)
    at = start.astimezone(UTC) + timedelta(seconds=10)
    assert n.check(at) == [] and manager.snapshot()["toast"] != "Time to start: CASL metrics"  # no interruption
    assert n.check(at + timedelta(minutes=5)) == []  # still focusing: still quiet
    manager.complete_step()  # natural break: step done
    said = n.check(at + timedelta(minutes=6))
    h = start.hour % 12 or 12
    assert said == [f"When you're ready: Send CASL consent metrics to Priya was planned for "
                    f"{h}:{start.minute:02d}." if start.minute else
                    f"When you're ready: Send CASL consent metrics to Priya was planned for {h} o'clock."]
    assert manager.snapshot()["toast"] == f"Next: CASL metrics ({start.strftime('%H:%M')})"
    assert n.check(at + timedelta(minutes=7)) == []  # said once
    assert manager.active_task()["id"] == rep and casl != rep  # nothing was switched for the user


def test_no_start_nudge_for_the_task_already_in_hand(manager) -> None:  # type: ignore[no-untyped-def]
    start = datetime.now(manager.tz).replace(second=0, microsecond=0) + timedelta(minutes=10)
    manager.commit_plan(_plan(start.strftime("%Y-%m-%dT%H:%M")), "casl")  # becomes the active task
    manager.timer_start()
    assert NudgeScheduler(manager).check(start.astimezone(UTC) + timedelta(seconds=10)) == []
