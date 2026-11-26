"""Meetings -> Graph: meetings, summaries, people and topics as nodes and edges (meetings/graph.py)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from service.config import Settings
from service.main import create_app
from service.meetings.graph import build_graph, topic_catalog


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


def _edges(g: dict) -> dict[tuple[str, str], str]:  # type: ignore[type-arg]
    return {(e["source"], e["target"]): e["kind"] for e in g["edges"]}


def test_a_topic_that_names_a_person_links_to_that_person() -> None:
    a = _m("a", "Onboarding", ["Priya Smith", "Ana"], {"summary": "Priya's first week.", "topics": ["Onboarding"]})
    b = _m("b", "Budget", ["Ana"], {"summary": "Ask Priya about Q3.", "topics": ["Q3 budget", "Priya", "Oskar"]})
    c = _m("c", "Vendors", ["Ana"], {"summary": "Oskar sent the quote.", "topics": ["Vendor quotes"]})
    g = build_graph([a, b, c], vocabulary=["Oskar"], people=["Oskar"])  # Oskar: a remembered voice, never a speaker here
    nodes = {n["id"]: n for n in g["nodes"]}
    edges = _edges(g)
    assert "topic:priya" not in nodes and "topic:oskar" not in nodes
    assert nodes["person:priya smith"]["meetings"] == ["a"]                 # attended a ...
    assert nodes["person:priya smith"]["mentioned"] == ["b"]                # ... talked about in b (unique first name)
    assert edges[("summary:b", "person:priya smith")] == "mentioned"
    assert nodes["person:oskar"]["meetings"] == [] and nodes["person:oskar"]["mentioned"] == ["b", "c"]
    assert edges[("summary:c", "person:oskar")] == "mentioned"               # found by the vocabulary word too
    assert "mentioned" not in nodes["person:ana"]                           # attended: no extra mention edge


def test_a_shared_first_name_is_not_guessed() -> None:
    a = _m("a", "One", ["Sam Lee", "Sam Ortiz"], {"summary": "x", "topics": ["Hiring"]})
    b = _m("b", "Two", ["Ana"], {"summary": "y", "topics": ["Sam"]})
    nodes = {n["id"] for n in build_graph([a, b], [])["nodes"]}
    assert "topic:sam" in nodes  # two Sams: nobody to link it to


def test_differently_worded_topics_join_and_related_ones_link() -> None:
    a = _m("a", "One", ["Ana"], {"summary": "x", "topics": ["QR codes", "Report regression testing",
                                                            "Salesforce integration", "User permissions ticket"]})
    b = _m("b", "Two", ["Ana"], {"summary": "y", "topics": ["QR code", "Regression testing challenges",
                                                            "SMS consent in Salesforce", "Email ticket automation"]})
    c = _m("c", "Three", ["Ana"], {"summary": "z", "topics": ["qr code review"]})
    g = build_graph([a, b, c], [])
    nodes = {n["id"]: n for n in g["nodes"]}
    edges = _edges(g)
    qr = nodes["topic:qr code"]                    # one subject; named by the plainest wording
    assert qr["meetings"] == ["a", "b", "c"] and qr["aliases"] == ["qr code review", "QR codes"]
    assert "topic:qr codes" not in nodes
    rt = nodes["topic:report regression testing"]  # 2 core words inside 3: one subject
    assert rt["meetings"] == ["a", "b"] and rt["aliases"] == ["Regression testing challenges"]
    sf = ("topic:salesforce integration", "topic:sms consent in salesforce")
    assert edges.get(sf) == "related" or edges.get(sf[::-1]) == "related"
    tk = ("topic:user permissions ticket", "topic:email ticket automation")
    assert tk not in edges and tk[::-1] not in edges  # "ticket" alone is too vague to relate them
    assert "topic:salesforce integration" in nodes and "topic:sms consent in salesforce" in nodes  # not merged


def test_topic_catalog_lists_names_in_use_without_people() -> None:
    a = _m("a", "One", ["Priya"], {"summary": "x", "topics": ["Q3 budget", "Hiring"]}, started_at="2026-11-20T10:00:00Z")
    b = _m("b", "Two", ["Ana"], {"summary": "y", "topics": ["Q3 budgets", "Priya", "Launch"]},
           started_at="2026-11-24T10:00:00Z")
    c = _m("c", "Old", ["Ana"], {"summary": "z", "topics": ["Archived thing"]}, archived=1)
    assert topic_catalog([a, b, c]) == ["Q3 budget", "Launch", "Hiring"]


def test_summaries_are_told_the_topics_in_use(tmp_path: Path) -> None:
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    with TestClient(create_app(s)) as c:
        meetings = c.app.state.services.meetings  # type: ignore[attr-defined]
        old = meetings.repo.create("Budget", "2026-11-20T10:00:00Z", "UTC", str(tmp_path / "a.wav"), status="READY")
        meetings.repo.update(old, summary_json=json.dumps({"summary": "x", "topics": ["Q3 budget"]}),
                             summary_status="READY")
        new = meetings.repo.create("Next", "2026-11-25T10:00:00Z", "UTC", str(tmp_path / "b.wav"), status="READY")
        ctx = meetings._context(meetings.repo.get(new))
        assert "Topics already used in earlier meetings: Q3 budget" in ctx
        assert "Topics already used" not in meetings._context(meetings.repo.get(old))  # not its own topics
