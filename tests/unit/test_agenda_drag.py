"""Today page drag and drop: items move between Today and Tomorrow and onto Parked tangents."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from service.config import Settings
from service.main import create_app
from service.planner.schema import PlannerOutputV1

TZ = ZoneInfo("America/Toronto")


def _client(tmp_path: Path) -> TestClient:
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    return TestClient(create_app(s))


def _plan(title: str) -> PlannerOutputV1:
    return PlannerOutputV1.model_validate({"intent": "CREATE_TASK", "active_task": {"title": title, "steps": [
        {"title": "Open the CST database", "duration_min": 2, "is_starter": True},
        {"title": "Pull the CASL numbers", "duration_min": 10}, {"title": "Email them to Priya", "duration_min": 5}]}})


def test_drag_items_between_today_tomorrow_and_parked(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as c:
        m = c.app.state.services.manager  # type: ignore[attr-defined]
        today = datetime.now(TZ).date()
        tomorrow = (today + timedelta(days=1)).isoformat()
        tid = m.commit_plan(_plan("Send CASL metrics to Priya"), "casl")["task_id"]
        m.complete_step()  # the starter is done, 1 step in progress
        m.start_next_step()
        # the task in progress -> Tomorrow: set down (not active), steps kept
        assert c.post("/api/v1/agenda/move", json={"kind": "task", "id": tid, "date": tomorrow}).status_code == 200
        st = c.get("/api/v1/state").json()
        assert st["active_task"] is None and st["timer"]["state"] == "STOPPED"
        t = m.tasks.get_task(tid)
        assert t["target_date"] == tomorrow and t["status"] == "SCHEDULED" and t["steps"][0]["status"] == "COMPLETED"
        # a reminder keeps its time of day on the new date
        due = datetime.combine(today, datetime.min.time(), tzinfo=TZ).replace(hour=15, minute=30)
        rid = m.tasks.add_reminder("Call the dentist", due.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), TZ.key)
        assert c.post("/api/v1/agenda/move", json={"kind": "reminder", "id": rid, "date": tomorrow}).status_code == 200
        r = m.tasks.reminders()[0]
        moved = datetime.strptime(r["due_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(TZ)
        assert (moved.date().isoformat(), moved.strftime("%H:%M")) == (tomorrow, "15:30")
        # a one-time alarm too; a weekly one can't move to a single day
        a = c.post("/api/v1/alarms", json={"title": "Gym", "local_hhmm": "06:00", "fire_date": tomorrow}).json()
        assert c.post("/api/v1/agenda/move", json={"kind": "alarm", "id": a["id"], "date": today.isoformat()}).status_code == 200
        assert m.alarms.get(a["id"])["fire_utc"].startswith(today.isoformat())
        w = c.post("/api/v1/alarms", json={"title": "Weekday", "local_hhmm": "07:00", "schedule_kind": "RECURRING",
                                           "rrule_days": "MO,TU"}).json()
        assert c.post("/api/v1/agenda/move", json={"kind": "alarm", "id": w["id"], "date": tomorrow}).status_code == 409
        # onto Parked tangents: the task keeps its steps (Resume), a reminder becomes a note
        assert c.post("/api/v1/agenda/park", json={"kind": "task", "id": tid}).status_code == 200
        assert c.post("/api/v1/agenda/park", json={"kind": "reminder", "id": rid}).status_code == 200
        parked = {p["title"]: p for p in c.get("/api/v1/state").json()["parked"]}
        assert parked["Send CASL metrics to Priya"]["task_id"] == tid and "Call the dentist" in parked
        assert m.tasks.reminders() == []
        # ...and back onto Today: the parked task resumes with its steps
        r = c.post(f"/api/v1/parked/{parked['Send CASL metrics to Priya']['id']}/promote").json()
        assert r == {"task_id": tid, "resumed": True}
        assert m.tasks.get_task(tid)["target_date"] == today.isoformat()
        assert c.post("/api/v1/agenda/move", json={"kind": "task", "id": "nope", "date": tomorrow}).status_code == 404


def test_new_task_while_another_runs_says_where_it_went(manager) -> None:  # type: ignore[no-untyped-def]
    manager.commit_plan(_plan("Send CASL metrics to Priya"), "a")
    first = manager.active_task()["id"]
    p = _plan("Ask Priya about the rep ID")
    p.active_task.short_title = "Rep ID question"  # type: ignore[union-attr]
    manager.commit_plan(p, "b")
    assert manager.active_task()["id"] == first  # the one in progress stays
    assert manager.snapshot()["toast"] == "Added to today: Rep ID question"
