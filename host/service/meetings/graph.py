"""The meetings graph (Meetings -> Graph in the app): the same links the Obsidian notes make, as nodes and edges.

Nodes: every meeting (its transcript), its summary (when there is one), the people in it (named speakers only -
"Speaker 01" is not a person, as in obsidian.py) and its topics (the summary's topics plus the user's vocabulary words
that come up in the title or summary). Edges: meeting - summary, meeting - person, summary - topic (a meeting without
a summary links its vocabulary topics itself). People and topics shared by several meetings join them, so the graph
shows who meets about what. Keys match Obsidian's link targets, so "Ana" here is [[Ana]] there.

No transcripts are read: the graph is cheap enough to rebuild on every meeting change."""
from __future__ import annotations

import json
import re
from typing import Any

from .obsidian import is_person, safe_name

GIST_CHARS = 160


def _key(kind: str, name: str) -> str:
    return f"{kind}:{safe_name(name, 60).lower()}"


def _gist(summary: dict[str, Any]) -> str:
    text = (summary.get("outcome") or summary.get("summary") or "").strip()
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= GIST_CHARS else first[:GIST_CHARS - 1].rstrip() + "…"


def _topics(meeting: dict[str, Any], people: set[str], vocabulary: list[str]) -> list[str]:
    summary = meeting.get("summary") or {}
    out: dict[str, str] = {}
    for t in summary.get("topics") or []:
        if isinstance(t, str) and t.strip() and t.lower() not in people:
            out.setdefault(t.strip().lower(), t.strip())
    text = meeting["title"] + " " + json.dumps(summary, ensure_ascii=False)
    for w in vocabulary:
        if w.lower() not in people and re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.I):
            out.setdefault(w.lower(), w)
    return list(out.values())[:12]


def build_graph(meetings: list[dict[str, Any]], vocabulary: list[str],
                include_archived: bool = False) -> dict[str, Any]:
    """meetings: repo.all_with_summaries() rows (summary + speakers). Returns {nodes, edges, counts}."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def edge(a: str, b: str, kind: str) -> None:
        if (a, b) not in seen:
            seen.add((a, b))
            edges.append({"source": a, "target": b, "kind": kind})

    def shared(kind: str, name: str, mid: str) -> str:
        key = _key(kind, name)
        n = nodes.setdefault(key, {"id": key, "kind": kind, "label": name.strip(), "meetings": []})
        if mid not in n["meetings"]:
            n["meetings"].append(mid)
        return key

    for m in meetings:
        if m.get("archived") and not include_archived:
            continue
        summary = m.get("summary") or None
        actions = (summary or {}).get("action_items") or []
        mkey = f"meeting:{m['id']}"
        nodes[mkey] = {
            "id": mkey, "kind": "meeting", "label": m["title"], "meeting_id": m["id"], "started_at": m["started_at"],
            "duration_s": m.get("duration_s") or 0, "status": m["status"], "archived": bool(m.get("archived")),
            "summary_status": m.get("summary_status") or "NONE",
        }
        hub = mkey
        if summary:
            skey = f"summary:{m['id']}"
            nodes[skey] = {
                "id": skey, "kind": "summary", "label": f"Summary · {m['title']}", "meeting_id": m["id"],
                "gist": _gist(summary), "engine": m.get("summary_engine"),
                "open_actions": sum(1 for a in actions if not a.get("done") and a.get("status") != "dismissed"),
                "archived": bool(m.get("archived")),
            }
            edge(mkey, skey, "summary")
            hub = skey
        names = [sp["name"].strip() for sp in m.get("speakers", []) if is_person(sp["name"])]
        for name in dict.fromkeys(names):
            edge(mkey, shared("person", name, m["id"]), "attended")
        for t in _topics(m, {n.lower() for n in names}, vocabulary):
            edge(hub, shared("topic", t, m["id"]), "topic")

    counts: dict[str, int] = {}
    for n in nodes.values():
        counts[n["kind"]] = counts.get(n["kind"], 0) + 1
    return {"nodes": list(nodes.values()), "edges": edges, "counts": counts}
