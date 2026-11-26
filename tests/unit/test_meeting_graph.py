"""Meetings -> Graph: meetings, summaries, people and topics as nodes and edges (meetings/graph.py)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from service.config import Settings
from service.main import create_app
from service.meetings.graph import build_graph


def _m(mid: str, title: str, speakers: list[str], summary: dict | None = None, **kw) -> dict:  # type: ignore[type-arg]
    return {"id": mid, "title": title, "started_at": "2026-11-25T10:00:00Z", "duration_s": 600, "status": "READY",
            "summary": summary, "summary_status": "READY" if summary else "NONE", "summary_engine": "local/qwen3:8b",
            "speakers": [{"key": f"S{i + 1}", "name": n} for i, n in enumerate(speakers)], **kw}


def test_people_and_topics_join_meetings() -> None:
    a = _m("a", "Budget sync", ["Ana", "Speaker 02"], {
        "summary": "We went over the Q3 budget. Then lunch.", "topics": ["Q3 budget", "Hiring", "ana"],
        "action_items": [{"task": "Send deck", "done": False}, {"task": "Old", "done": True},
                         {"task": "Nope", "status": "dismissed"}]})
    b = _m("b", "Hiring chat", ["ana ", "Jordan"], {"summary": "Hiring plan.", "topics": ["hiring"]})
    c = _m("c", "Untitled about Atlas", ["Jordan"])  # no summary: vocabulary topic hangs off the meeting
    g = build_graph([a, b, c], vocabulary=["Atlas"])
    nodes = {n["id"]: n for n in g["nodes"]}
    edges = {(e["source"], e["target"]) for e in g["edges"]}

    assert g["counts"] == {"meeting": 3, "summary": 2, "person": 2, "topic": 3}
    assert "person:speaker 02" not in nodes                      # default speaker names are not people
    assert nodes["person:ana"]["meetings"] == ["a", "b"]         # same person across meetings (case/space-insensitive)
    assert "topic:ana" not in nodes                              # a topic that is a person's name is dropped
    assert nodes["topic:hiring"]["meetings"] == ["a", "b"]
    assert ("summary:a", "topic:q3 budget") in edges and ("meeting:a", "summary:a") in edges
    assert ("meeting:c", "topic:atlas") in edges and ("meeting:c", "person:jordan") in edges
    assert nodes["summary:a"]["gist"] == "We went over the Q3 budget."
    assert nodes["summary:a"]["open_actions"] == 1


def test_archived_meetings_are_left_out_unless_asked() -> None:
    ms = [_m("a", "Kept", ["Ana"]), _m("b", "Old", ["Ana"], archived=1)]
    assert [n["id"] for n in build_graph(ms, [])["nodes"] if n["kind"] == "meeting"] == ["meeting:a"]
    g = build_graph(ms, [], include_archived=True)
    assert {n["id"] for n in g["nodes"] if n["kind"] == "meeting"} == {"meeting:a", "meeting:b"}
    assert next(n for n in g["nodes"] if n["id"] == "person:ana")["meetings"] == ["a", "b"]


def test_graph_endpoint(tmp_path: Path) -> None:
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    with TestClient(create_app(s)) as c:
        repo = c.app.state.services.meetings.repo  # type: ignore[attr-defined]
        mid = repo.create("Launch review", "2026-11-25T10:00:00Z", "UTC", str(tmp_path / "x.wav"), status="READY")
        repo.replace_transcript(mid, [{"start_s": 0, "end_s": 2, "text": "Hi", "speaker_key": "S1"}],
                                [{"key": "S1", "name": "Ana"}, {"key": "S2", "name": "Speaker 02"}])
        repo.update(mid, summary_json=json.dumps({"summary": "Ship it.", "topics": ["Launch"], "action_items": []}),
                    summary_status="READY")
        g = c.get("/api/v1/meetings/graph").json()
        assert {n["id"] for n in g["nodes"]} == {f"meeting:{mid}", f"summary:{mid}", "person:ana", "topic:launch"}
        repo.update(mid, archived=1)
        assert c.get("/api/v1/meetings/graph").json()["nodes"] == []
        assert len(c.get("/api/v1/meetings/graph?archived=true").json()["nodes"]) == 4
