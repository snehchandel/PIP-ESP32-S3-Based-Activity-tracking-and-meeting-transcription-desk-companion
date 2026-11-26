"""The meetings graph (Meetings -> Graph in the app): the same links the Obsidian notes make, as nodes and edges.

Nodes: every meeting (its transcript), its summary (when there is one), the people in it (named speakers only -
"Speaker 01" is not a person, as in obsidian.py) and its topics (the summary's topics plus the user's vocabulary words
that come up in the title or summary). Edges: meeting - summary, meeting - person ("attended"), summary - topic (a
meeting without a summary links its vocabulary topics itself). People and topics shared by several meetings join
them, so the graph shows who meets about what. Keys match Obsidian's link targets, so "Ana" here is [[Ana]] there.

Topics are joined across meetings (ADR-037), because each summary words them its own way:
- A topic that is a known person's name (a named speaker of any meeting or a remembered voice, or that person's
  unique first name) is not a topic: the meeting links to the person instead ("mentioned").
- Topics with the same core words (case, plurals, filler words such as "review" or "setup" ignored) are one node,
  and so is a topic whose 2+ core words are all inside another ("Regression testing" joins "Report regression
  testing"). The node is named after the wording used most; the others are kept as `aliases`.
- Topics from different meetings that share a distinctive word ("Salesforce integration", "SMS consent in
  Salesforce") stay apart but get a "related" edge (at most 3 per topic).
`topic_catalog()` gives the summarizers the names already in use, so new summaries reuse them.

No transcripts are read: the graph is cheap enough to rebuild on every meeting change."""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from .obsidian import is_person, safe_name

GIST_CHARS = 160
TOPICS_PER_MEETING = 12
RELATED_PER_TOPIC = 3
COMMON_WORD_TOPICS = 6  # a word in more topics than this says nothing about how they relate

_STOP = {"a", "an", "and", "the", "of", "for", "in", "on", "to", "with", "about", "vs", "via", "at", "by", "from",
         "our", "new", "next", "its", "into", "per"}
_GENERIC = {"review", "setup", "set", "up", "management", "discussion", "update", "overview", "status", "challenge",
            "issue", "problem", "question", "item", "topic", "meeting", "session", "sync", "call", "general", "misc",
            "ongoing", "current", "process", "progress", "work", "plan", "planning", "strategy", "detail", "check",
            "option", "idea", "concern", "follow", "followup", "next", "step", "approach", "handling"}
# words too vague to relate two topics by themselves ("sign-up" vs "sign-off", "permissions ticket" vs "ticket
# automation"); they still count for joining topics
_WEAK = {"sign", "off", "ticket", "verification", "tracking", "request", "project", "requirement", "scope", "role",
         "standardization", "inventory", "transfer", "knowledge", "development", "team", "time", "list", "form",
         "field", "visibility", "report", "change", "support", "task", "work", "data", "access", "user", "need"}


def _key(kind: str, name: str) -> str:
    return f"{kind}:{safe_name(name, 60).lower()}"


def _gist(summary: dict[str, Any]) -> str:
    text = (summary.get("outcome") or summary.get("summary") or "").strip()
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= GIST_CHARS else first[:GIST_CHARS - 1].rstrip() + "…"


def _singular(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def core(label: str) -> frozenset[str]:
    """The words that say what a topic is about: lower case, singular, without filler words."""
    words = [_singular(w) for w in re.findall(r"[a-z0-9]+", label.lower())]
    content = [w for w in words if w not in _STOP]
    return frozenset(w for w in content if w not in _GENERIC) or frozenset(content) or frozenset(words)


def _distinctive(w: str) -> bool:
    return (len(w) >= 4 or any(c.isdigit() for c in w)) and w not in _GENERIC and w not in _STOP and w not in _WEAK


class People:
    """Known people: lower-case name -> name as written, plus first names that belong to exactly one person."""

    def __init__(self, names: Iterable[str]) -> None:
        self.full: dict[str, str] = {}
        firsts: dict[str, set[str]] = {}
        for n in names:
            n = " ".join(str(n or "").split())
            if is_person(n) and n.lower() not in self.full:
                self.full[n.lower()] = n
                firsts.setdefault(n.lower().split()[0], set()).add(n)
        self.first = {f: next(iter(ns)) for f, ns in firsts.items() if len(ns) == 1}

    def match(self, label: str) -> str | None:
        """The person a topic names ("Priya", "priya smith"), else None."""
        s = " ".join(label.lower().split()).strip(" .'\"")
        s = re.sub(r"'s$", "", s)
        return self.full.get(s) or (self.first.get(s) if " " not in s else None)


def _raw_topics(meeting: dict[str, Any], vocabulary: list[str]) -> list[str]:
    summary = meeting.get("summary") or {}
    out: dict[str, str] = {}
    for t in summary.get("topics") or []:
        if isinstance(t, str) and t.strip():
            out.setdefault(t.strip().lower(), " ".join(t.split()))
    text = meeting["title"] + " " + json.dumps(summary, ensure_ascii=False)
    for w in vocabulary:
        if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.I):
            out.setdefault(w.lower(), w)
    return list(out.values())


class _Clusters:
    """Topic wordings joined into subjects (union-find over core word sets)."""

    def __init__(self, labels: Iterable[str]) -> None:
        self.cores: dict[str, frozenset[str]] = {}
        for lab in labels:
            self.cores.setdefault(lab.lower(), core(lab))
        self.parent = {k: k for k in self.cores}
        keys = list(self.cores)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                ca, cb = self.cores[a], self.cores[b]
                small, big = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
                if ca == cb or (len(small) >= 2 and small <= big):
                    self.parent[self.find(b)] = self.find(a)

    def find(self, k: str) -> str:
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k


def _subjects(per_meeting: dict[str, list[str]]) -> dict[str, str]:
    """topic wording (lower) -> the name of its subject: the wording used in most meetings, then the shortest
    ("QR code" over "QR codes")."""
    labels = [t for ts in per_meeting.values() for t in ts]
    cl = _Clusters(labels)
    uses: dict[str, set[str]] = {}
    shown: dict[str, str] = {}
    for mid, ts in per_meeting.items():
        for t in ts:
            uses.setdefault(t.lower(), set()).add(mid)
            shown.setdefault(t.lower(), t)
    groups: dict[str, list[str]] = {}
    for k in shown:
        groups.setdefault(cl.find(k), []).append(k)
    name: dict[str, str] = {}
    for members in groups.values():
        best = min(members, key=lambda k: (-len(uses[k]), len(k.split()), len(k), labels.index(shown[k])))
        for k in members:
            name[k] = shown[best]
    return name


def topic_catalog(meetings: list[dict[str, Any]], people: Iterable[str] = (), limit: int = 30) -> list[str]:
    """Topic names already used by the summaries (most meetings first, then most recent): handed to the summarizers
    so a new summary says "Q3 budget" again rather than "Budget for Q3"."""
    rows = sorted((m for m in meetings if m.get("summary") and not m.get("archived")),
                  key=lambda m: str(m.get("started_at") or ""), reverse=True)
    known = People([*people, *(sp["name"] for m in meetings for sp in m.get("speakers") or [])])
    per = {m["id"]: [t for t in _raw_topics(m, []) if not known.match(t)] for m in rows}
    name = _subjects(per)
    score: dict[str, tuple[int, int]] = {}
    for rank, m in enumerate(rows):
        for t in {name[t.lower()] for t in per[m["id"]]}:
            n, first = score.get(t, (0, rank))
            score[t] = (n + 1, min(first, rank))
    return sorted(score, key=lambda t: (-score[t][0], score[t][1]))[:limit]


def build_graph(meetings: list[dict[str, Any]], vocabulary: list[str], include_archived: bool = False,
                people: Iterable[str] = ()) -> dict[str, Any]:
    """meetings: repo.all_with_summaries() rows (summary + speakers); people: other known names (remembered voices).
    Returns {nodes, edges, counts}."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    # people known from every meeting (archived ones too: a person stays a person) and the remembered voices
    known = People([*(sp["name"] for m in meetings for sp in m.get("speakers") or []), *people])
    shown = [m for m in meetings if include_archived or not m.get("archived")]

    def edge(a: str, b: str, kind: str) -> None:
        if (a, b) not in seen and (b, a) not in seen:
            seen.add((a, b))
            edges.append({"source": a, "target": b, "kind": kind})

    def shared(kind: str, name: str, mid: str, field: str = "meetings") -> str:
        key = _key(kind, name)
        n = nodes.setdefault(key, {"id": key, "kind": kind, "label": name.strip(), "meetings": []})
        lst = n.setdefault(field, [])
        if mid not in lst:
            lst.append(mid)
        return key

    attended: dict[str, list[str]] = {}
    mentions: dict[str, list[str]] = {}
    topics: dict[str, list[str]] = {}
    for m in shown:
        names = [known.match(sp["name"]) or sp["name"].strip() for sp in m.get("speakers", []) if is_person(sp["name"])]
        attended[m["id"]] = list(dict.fromkeys(names))
        here = {n.lower() for n in attended[m["id"]]}
        mentions[m["id"]], topics[m["id"]] = [], []
        for t in _raw_topics(m, vocabulary):
            who = known.match(t)
            if who is None:
                topics[m["id"]].append(t)
            elif who.lower() not in here and who not in mentions[m["id"]]:
                mentions[m["id"]].append(who)
        topics[m["id"]] = topics[m["id"]][:TOPICS_PER_MEETING]
    subject = _subjects(topics)
    aliases: dict[str, set[str]] = {}

    for m in shown:
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
        for name in attended[m["id"]]:
            edge(mkey, shared("person", name, m["id"]), "attended")
        for name in mentions[m["id"]]:
            edge(hub, shared("person", name, m["id"], "mentioned"), "mentioned")
        for t in topics[m["id"]]:
            label = subject[t.lower()]
            edge(hub, shared("topic", label, m["id"]), "topic")
            if t.lower() != label.lower():
                aliases.setdefault(_key("topic", label), set()).add(t)

    for key, names in aliases.items():
        nodes[key]["aliases"] = sorted(names, key=str.lower)
    _related(nodes, edge)

    counts: dict[str, int] = {}
    for n in nodes.values():
        counts[n["kind"]] = counts.get(n["kind"], 0) + 1
    return {"nodes": list(nodes.values()), "edges": edges, "counts": counts}


def _related(nodes: dict[str, dict[str, Any]], edge: Any) -> None:
    """Topic - topic edges between subjects of different meetings that share a distinctive word."""
    tops = [n for n in nodes.values() if n["kind"] == "topic"]
    words = {n["id"]: {w for lab in [n["label"], *n.get("aliases", [])] for w in core(lab) if _distinctive(w)}
             for n in tops}
    spread: dict[str, int] = {}
    for ws in words.values():
        for w in ws:
            spread[w] = spread.get(w, 0) + 1
    pairs: list[tuple[int, int, str, str]] = []
    for i, a in enumerate(tops):
        for b in tops[i + 1:]:
            common = {w for w in words[a["id"]] & words[b["id"]] if spread[w] <= COMMON_WORD_TOPICS}
            if common and set(a["meetings"]) != set(b["meetings"]):
                pairs.append((-len(common), -(len(a["meetings"]) + len(b["meetings"])), a["id"], b["id"]))
    per: dict[str, int] = {}
    for _, _, a, b in sorted(pairs):
        if per.get(a, 0) < RELATED_PER_TOPIC and per.get(b, 0) < RELATED_PER_TOPIC:
            per[a], per[b] = per.get(a, 0) + 1, per.get(b, 0) + 1
            edge(a, b, "related")
