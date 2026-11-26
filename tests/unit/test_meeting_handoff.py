"""Summaries by another AI agent (ADR-036): the "ai" export (prompt + transcript), the lenient reader of the agent's
Markdown reply, and the upload that makes it the meeting's summary."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from service.config import Settings
from service.main import create_app
from service.meetings.handoff import PROMPT, handoff_md, parse_summary_md
from service.meetings.summarize import clean

EXACT = """# Q3 budget review

## Outcome
They agreed to hold the hiring plan until January.

## Summary
The team met to review the budget. Sam showed the numbers and Ana asked about hiring.

## Key points
- [00:05] Sam presented the Q3 spend.
- 00:10 - Ana asked about the hiring plan.

## Topics
- Q3 budget
- Hiring plan

## Decisions
- Hold hiring until January

## Action items
- [ ] [00:10] Send the revised forecast | Owner: Sam | Due: Friday
- [ ] Book the room for the offsite (Owner: Ana, due: next week)
- [ ] Share the slides — Owner: none — Due: none
"""


def test_prompt_asks_for_markdown_in_the_format_the_reader_expects() -> None:
    assert "No markdown" not in PROMPT and "## Action items" in PROMPT and "| Owner:" in PROMPT
    assert "ACTION ITEM" in PROMPT  # the same definitions the local summariser uses


def test_exact_format_is_read_completely() -> None:
    d = parse_summary_md(EXACT)
    assert d["title"] == "Q3 budget review"
    assert d["outcome"].startswith("They agreed") and d["summary"].startswith("The team met")
    assert d["key_points"] == ["[00:05] Sam presented the Q3 spend.", "[00:10] Ana asked about the hiring plan."]
    assert d["topics"] == ["Q3 budget", "Hiring plan"] and d["decisions"] == ["Hold hiring until January"]
    a = d["action_items"]
    assert a[0] == {"task": "Send the revised forecast", "said_at": "00:10", "owner": "Sam", "due": "Friday"}
    assert a[1] == {"task": "Book the room for the offsite", "said_at": None, "owner": "Ana", "due": "next week"}
    c = clean(d, "Meeting", ["Sam", "Ana"])
    assert c["action_items"][2]["owner"] is None and c["action_items"][2]["due"] is None  # "none" -> empty


def test_bold_labels_synonyms_and_nested_fields() -> None:
    d = parse_summary_md("""**Meeting Summary: Vendor call**

**Summary:** We talked to the vendor about pricing.

**Next steps:**
1. Email the vendor the contract
   - Owner: Jo
   - Due: Monday
2. Check the legal terms (12:30)

Agreements:
* Stay with the current vendor
""")
    assert d["title"] == "Vendor call" and d["summary"] == "We talked to the vendor about pricing."
    assert d["action_items"] == [
        {"task": "Email the vendor the contract", "said_at": None, "owner": "Jo", "due": "Monday"},
        {"task": "Check the legal terms", "said_at": "12:30", "owner": None, "due": None}]
    assert d["decisions"] == ["Stay with the current vendor"]


def test_fenced_reply_front_matter_and_json() -> None:
    fenced = parse_summary_md("```markdown\n---\ntitle: \"Weekly sync\"\n---\n## TL;DR\nAll on track.\n```")
    assert fenced["title"] == "Weekly sync" and fenced["summary"] == "All on track."
    js = parse_summary_md('```json\n{"title": "Sync", "summary": "All good.", "action_items": []}\n```')
    assert js["title"] == "Sync" and js["summary"] == "All good."
    only_points = parse_summary_md("## Highlights\n- [01:00] Ana opened the call.\n- [02:00] Sam closed it.")
    assert only_points["summary"] == "Ana opened the call. Sam closed it."  # no summary written: from the points


def test_text_that_is_not_a_summary_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_summary_md("Sure! Here is what I think about your meeting.\nIt went well.")


def _app(tmp_path: Path) -> TestClient:
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    return TestClient(create_app(s))


def test_handoff_export_and_upload_round_trip(tmp_path: Path) -> None:
    with _app(tmp_path) as c:
        svc = c.app.state.services.meetings  # type: ignore[attr-defined]
        mid = svc.repo.create("Meeting · Tue 10:00", "2026-11-24T15:00:00Z", "America/Toronto", "", status="READY")
        svc.repo.replace_transcript(mid, [
            {"start_s": 5.0, "end_s": 9.0, "text": "Here is the Q3 spend.", "speaker_key": "S1"},
            {"start_s": 10.0, "end_s": 14.0, "text": "I'll send the revised forecast by Friday.", "speaker_key": "S2"},
        ], [{"key": "S1", "name": "Ana"}, {"key": "S2", "name": "Sam"}])
        svc.repo.update(mid, duration_s=15.0)

        r = c.get(f"/api/v1/meetings/{mid}/export?format=ai")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
        assert '_for_AI.md"' in r.headers["content-disposition"]
        assert r.text.startswith("# Instructions for the AI") and "[00:10] **Sam**: I'll send the revised" in r.text
        assert c.get("/api/v1/meetings/summary-prompt").json()["prompt"] == PROMPT

        # a local summary waiting in the queue is dropped: the uploaded one must not be overwritten
        with svc._lock:
            svc._sq.append(mid)
        svc.repo.update(mid, summary_status="QUEUED")
        assert c.post(f"/api/v1/meetings/{mid}/summary/upload", content=b"just chatter").status_code == 422
        r = c.post(f"/api/v1/meetings/{mid}/summary/upload?source=Claude", content=EXACT.encode("utf-8"))
        assert r.status_code == 200, r.text
        assert mid not in svc._sq
        m = c.get(f"/api/v1/meetings/{mid}").json()
        assert m["summary_status"] == "READY" and m["summary_engine"] == "upload/Claude"
        assert m["title"] == "Q3 budget review"  # a default title takes the summary's
        first = m["summary"]["action_items"][0]
        assert first["owner"] == "Sam" and first["due_date"] == "2026-11-27" and first["status"] == "new"
        assert c.get("/api/v1/meetings/actions").json()["items"]

        # what the user did with an item survives a re-upload
        assert c.patch(f"/api/v1/meetings/{mid}/actions/0", json={"status": "dismissed"}).status_code == 200
        c.post(f"/api/v1/meetings/{mid}/summary/upload", content=EXACT.encode("utf-8"))
        m = c.get(f"/api/v1/meetings/{mid}").json()
        assert m["summary_engine"] == "upload" and m["summary"]["action_items"][0]["status"] == "dismissed"

        svc.repo.update(mid, summary_status="SUMMARIZING")
        assert c.post(f"/api/v1/meetings/{mid}/summary/upload", content=EXACT.encode()).status_code == 409
        assert c.post("/api/v1/meetings/nope/summary/upload", content=EXACT.encode()).status_code == 404


def test_handoff_md_lists_facts_notes_and_every_turn() -> None:
    m = {"title": "Sync", "started_at": "2026-11-24T15:00:00Z", "ended_at": None, "timezone": "UTC",
         "duration_s": 75, "notes": "Bring the numbers", "speakers": [{"key": "S1", "name": "Ana"}]}
    segs = [{"start_s": 0.0, "end_s": 1.0, "text": "Hello.", "speaker_key": "S1"},
            {"start_s": 70.0, "end_s": 71.0, "text": "Bye.", "speaker_key": "S1"}]
    md = handoff_md(m, segs, ["Kubernetes"])
    assert "- Speakers: Ana" in md and "Kubernetes" in md and "Bring the numbers" in md
    assert "[00:00] **Ana**: Hello. Bye." in md  # one speaker's consecutive lines are one turn
