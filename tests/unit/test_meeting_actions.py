"""Meeting action items after the summary: due dates from the meeting's own date, mine vs other people's, turning
chosen items into tasks / reminders / parked tangents, undecided dated items on the calendar, and archived meetings
leaving search, questions, action lists and the calendar."""
from __future__ import annotations

import time
from datetime import date

from fastapi.testclient import TestClient
from service.config import Settings
from service.main import create_app
from service.meetings.actions import enrich, guess_my_name, is_mine
from service.meetings.due import resolve_due

from tests.support.fake_ollama import FakeOllama

TUE = date(2026, 11, 24)


def test_deadline_words_become_dates_from_the_meeting_day() -> None:
    def day(text: str) -> str | None:
        d = resolve_due(text, TUE)
        return d.day.isoformat() if d else None

    assert day("Friday") == "2026-11-27" and day("next Friday") == "2026-12-04"
    assert day("November 26th") == "2026-11-26" and day("by the 3rd") == "2026-12-03" and day("Jan 5") == "2027-01-05"
    assert day("tomorrow EOD") == "2026-11-25" and resolve_due("tomorrow EOD", TUE).at.hour == 17  # type: ignore[union-attr]
    assert resolve_due("November 27th noon", TUE).at.hour == 12  # type: ignore[union-attr]
    soft = resolve_due("next week", TUE)
    assert soft is not None and soft.day.isoformat() == "2026-11-30" and not soft.exact
    assert day("end of month") == "2026-11-30" and day("in two weeks") == "2026-12-08"
    assert day("soon") is None and day("Not specified") is None and day(None) is None


def test_mine_and_enrich() -> None:
    assert is_mine("Alex", "Alex") and is_mine("Jordan and Alex", "alex") and not is_mine("Jordan", "Alex")
    assert not is_mine(None, "Alex") and not is_mine("Alex", "")
    m = {"started_at": "2026-11-24T15:00:00Z", "timezone": "America/Toronto"}
    s = {"action_items": [{"task": "Send it", "owner": "Alex", "due": "Friday"},
                          {"task": "Book it", "owner": "Lee", "due": "soon", "due_user": True, "due_date": "2026-12-01"}]}
    enrich(s, m, "Alex")
    a, b = s["action_items"]
    assert a["due_date"] == "2026-11-27" and a["mine"] and a["status"] == "new"
    assert b["due_date"] == "2026-12-01" and not b["mine"]  # a date the user set is kept
    assert guess_my_name([{"speakers": [{"name": "Alex"}, {"name": "Lee"}]}, {"speakers": [{"name": "Alex"}]},
                          {"speakers": [{"name": "Speaker 01"}]}]) == "Alex"


def _app(tmp_path, ollama):  # type: ignore[no-untyped-def]
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"),
                 pip_local_ai_url=ollama.url)
    return TestClient(create_app(s))


def _summarised_meeting(c: TestClient) -> str:
    svcs = c.app.state.services  # type: ignore[attr-defined]
    repo = svcs.meetings.repo
    mid = repo.create("Weekly sync", "2026-11-24T15:00:00Z", "America/Toronto", "", status="READY")
    repo.replace_transcript(mid, [
        {"start_s": 0, "end_s": 4, "text": "I'll send the Q3 budget by Friday.", "speaker_key": "S1"},
        {"start_s": 5, "end_s": 9, "text": "And I will book the client room next week.", "speaker_key": "S2"},
        {"start_s": 10, "end_s": 14, "text": "Let's also check the zebra migration.", "speaker_key": "S1"}],
        [{"key": "S1", "name": "Alex"}, {"key": "S2", "name": "Lee"}])
    summary = {"title": "Weekly sync", "summary": "Budget and room.", "decisions": [], "topics": ["Q3 budget"],
               "action_items": [{"task": "Send the Q3 budget", "owner": "Alex", "due": "Friday"},
                                {"task": "Book the client room", "owner": "Lee", "due": "next week"},
                                {"task": "Check the zebra migration", "owner": None, "due": None}]}
    svcs.meetings._save_summary(mid, summary, "local/test")
    return mid


def test_choose_what_each_action_item_becomes_and_see_dated_ones_on_the_calendar(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ollama = FakeOllama()
    with _app(tmp_path, ollama) as c:
        assert c.put("/api/v1/settings/meetings", json={"my_name": "Alex"}).json()["my_name"] == "Alex"
        mid = _summarised_meeting(c)
        time.sleep(0.2)  # "my name" re-check runs in the background
        items = c.get("/api/v1/meetings/actions").json()["items"]
        assert [(a["task"], a["mine"], a["due_date"]) for a in items] == [
            ("Send the Q3 budget", True, "2026-11-27"), ("Book the client room", False, "2026-11-30"),
            ("Check the zebra migration", False, None)]  # mine first
        # calendar: my dated item shows as "from meeting" (kind 3); Lee's only when asked for
        def week(others: bool = False) -> list[dict]:  # type: ignore[type-arg]
            days = c.get(f"/api/v1/calendar?start=2026-11-23&days=14&others={str(others).lower()}").json()
            return [i | {"date": d["date"]} for d in days for i in d["items"] if i["kind"] == 3]
        assert [(i["title"], i["date"]) for i in week()] == [("Send the Q3 budget", "2026-11-27")]
        assert {i["title"] for i in week(True)} == {"Send the Q3 budget", "Book the client room"}
        # the user moves my item to Thursday, then makes it a task; Lee's becomes a follow-up reminder at 10:00
        a = c.patch(f"/api/v1/meetings/{mid}/actions/0", json={"due_date": "2026-11-26"}).json()
        assert a["due_date"] == "2026-11-26" and a["due_user"]
        made = c.post(f"/api/v1/meetings/{mid}/actions/convert", json={"items": [
            {"index": 0, "as": "task"}, {"index": 1, "as": "reminder", "time": "10:00"}]}).json()["made"]
        assert [x["as"] for x in made] == ["task", "reminder"]
        cal = c.get("/api/v1/calendar?start=2026-11-23&days=14&others=true").json()
        by_day = {d["date"]: d["items"] for d in cal}
        assert any(i["kind"] == 0 and i["title"] == "Send the Q3 budget" for i in by_day["2026-11-26"])
        assert any(i["kind"] == 1 and i["hhmm"] == "10:00" for i in by_day["2026-11-30"])
        assert week(True) == []  # decided items leave the "from meeting" layer: no duplicates
        # converting twice does nothing; the undated one is parked; dismissing works
        assert c.post(f"/api/v1/meetings/{mid}/actions/convert", json={"items": [{"index": 0, "as": "task"}]}).json()["made"] == []
        assert c.post(f"/api/v1/meetings/{mid}/park-actions", json={"indexes": [2]}).json()["parked_ids"]
        statuses = [a["status"] for a in c.get(f"/api/v1/meetings/{mid}").json()["summary"]["action_items"]]
        assert statuses == ["task", "reminder", "parked"]
        assert c.patch(f"/api/v1/meetings/{mid}/actions/9", json={"status": "dismissed"}).status_code == 404
        assert c.post(f"/api/v1/meetings/{mid}/actions/convert", json={"items": [{"index": 0, "as": "x"}]}).status_code == 422
    ollama.close()


def test_archived_meetings_leave_search_questions_actions_and_calendar(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ollama = FakeOllama()
    with _app(tmp_path, ollama) as c:
        c.put("/api/v1/settings/meetings", json={"my_name": "Alex"})
        mid = _summarised_meeting(c)
        assert c.get("/api/v1/meetings/search?q=zebra").json()["hits"]
        assert c.post(f"/api/v1/meetings/{mid}/archive", json={"archived": True}).json()["archived"] is True
        assert c.get("/api/v1/meetings/search?q=zebra").json()["hits"] == []
        ans = c.post("/api/v1/meetings/ask", json={"question": "What about the zebra migration?"}).json()
        assert ans["sources"] == [] and len(ollama.chats) == 0  # nothing to answer from: no model call
        assert c.get("/api/v1/meetings/actions").json()["items"] == []
        assert len(c.get("/api/v1/meetings/actions?archived=true").json()["items"]) == 3
        days = c.get("/api/v1/calendar?start=2026-11-23&days=14&others=true").json()
        assert not [i for d in days for i in d["items"] if i["kind"] == 3]
        lst = c.get("/api/v1/meetings").json()["meetings"]
        assert lst[0]["id"] == mid and lst[0]["archived"] == 1  # still listed (in the Archived group of the app)
        c.post(f"/api/v1/meetings/{mid}/archive", json={"archived": False})
        assert c.get("/api/v1/meetings/search?q=zebra").json()["hits"]
    ollama.close()


def test_meeting_settings_quality_name_and_speech_model(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ollama = FakeOllama()
    with _app(tmp_path, ollama) as c:
        st = c.get("/api/v1/settings/meetings").json()
        assert st["summary_quality"] == "careful" and st["speech_model"] == "auto" and "large-v3-turbo" in st["speech_models"]
        st = c.put("/api/v1/settings/meetings", json={"summary_quality": "fast", "speech_model": "medium.en"}).json()
        assert st["summary_quality"] == "fast" and st["speech_model_active"] == "medium.en"
        assert c.app.state.services.meetings.stt.model_name == "medium.en"  # type: ignore[attr-defined]
        assert c.put("/api/v1/settings/meetings", json={"summary_quality": "best"}).status_code == 422
        _summarised_meeting(c)  # Alex and Lee once each: a tie, no guess
        assert c.get("/api/v1/settings/meetings").json()["my_name"] == ""
        repo = c.app.state.services.meetings.repo  # type: ignore[attr-defined]
        other = repo.create("1:1", "2026-11-25T15:00:00Z", "America/Toronto", "", status="READY")
        repo.replace_transcript(other, [{"start_s": 0, "end_s": 1, "text": "Hi", "speaker_key": "S1"}],
                                [{"key": "S1", "name": "Alex"}])
        st = c.get("/api/v1/settings/meetings").json()  # Alex is in most meetings: "me" until the user says otherwise
        assert st["my_name"] == "Alex" and not st["my_name_set"]
    ollama.close()
