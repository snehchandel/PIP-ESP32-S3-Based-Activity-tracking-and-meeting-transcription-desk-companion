"""Questions about meetings, answered from the few passages that matter (retrieval), never whole transcripts.

1. Search: the question's words -> SQLite FTS5 (porter stemming, bm25) over speaker turns and summary parts
   of every meeting. No AI, no tokens, milliseconds.
2. No hit -> "not found" without calling any model (the cheapest answer is the one never asked).
3. Context: for each hit, the turn plus the turns around it, grouped by meeting with its one-paragraph summary,
   capped at ~6,000 characters (~1,500 tokens) - versus ~15k tokens for a single hour of transcript.
4. One model call (local by default, Kimi on request) answers with [Meeting @ mm:ss] citations."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .export import _local, clock, speaker_turns
from .store import MeetingRepo

CONTEXT_CHARS = 6000
MAX_HITS = 14
STOP = set("""a about above after again all am an and any are as at be been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers him his how
i if in into is it its itself just me more most my no nor not now of off on once only or other our out over own
same she should so some such than that the their them then there these they this those through to too under until
up very was we were what when where which while who whom why will with would you your yours meeting meetings said
say says tell talked talk discussed discuss anything something did does someone anyone""".split())

ASK_PROMPT = """You answer questions about the user's meetings using ONLY the excerpts below (each excerpt starts
with its meeting and time). Cite every fact as [Meeting title @ mm:ss] (or [Meeting title] for summary lines).
If the excerpts do not contain the answer, say so in one sentence - never guess. Be brief: at most 6 sentences
or a short list. Plain text, no markdown headings."""

TextLLM = Callable[[str, str], str]  # (system, user) -> answer


def fts_query(question: str, any_word: bool = False) -> str:
    words = [w for w in re.findall(r"[\w']+", question.lower()) if len(w) > 1 and w not in STOP]
    words = list(dict.fromkeys(w.strip("'") for w in words if w.strip("'")))[:12]
    return (" OR " if any_word else " ").join(f'"{w}"' for w in words)


def search(repo: MeetingRepo, question: str, limit: int = 20, meeting_id: str | None = None) -> list[dict[str, Any]]:
    """Every word first (precise); if that finds nothing, any word (broad)."""
    for any_word in (False, True):
        q = fts_query(question, any_word)
        if not q:
            return []
        hits = repo.search(q, limit, meeting_id)
        if hits:
            for h in hits:
                start = _local(h.pop("started_at"), h.pop("timezone"))
                h["date"] = start.strftime("%Y-%m-%d %H:%M") if start else ""
                h["at"] = clock(h["start_s"]) if h["kind"] == "turn" else ""
            return hits
    return []


def build_context(repo: MeetingRepo, hits: list[dict[str, Any]], budget: int = CONTEXT_CHARS) -> tuple[str, list[dict[str, Any]]]:
    """Excerpts for the model + the sources they came from (best meetings first, each hit with its neighbours)."""
    by_meeting: dict[str, list[dict[str, Any]]] = {}
    for h in hits[:MAX_HITS]:
        by_meeting.setdefault(h["meeting_id"], []).append(h)
    blocks, sources, used = [], [], 0
    for mid, mh in by_meeting.items():
        m = repo.get(mid)
        if m is None:
            continue
        names = {sp["key"]: sp["name"] for sp in m["speakers"]}
        turns = speaker_turns(repo.segments(mid), names)
        starts = [t for _, t, _ in turns]
        lines = [f"## {m['title']} ({mh[0]['date']})"]
        if (m.get("summary") or {}).get("summary"):
            lines.append("Summary: " + m["summary"]["summary"][:500])
        picked: set[int] = set()
        for h in mh:
            if h["kind"] != "turn":
                if h["kind"] not in ("title", "summary"):
                    lines.append(f"{h['kind'].capitalize()}: {h['text'][:300]}")
                sources.append({"meeting_id": mid, "title": m["title"], "date": h["date"], "kind": h["kind"],
                                "start_s": None, "at": ""})
                continue
            i = min(range(len(starts)), key=lambda k: abs(starts[k] - h["start_s"])) if starts else -1
            for k in (i - 1, i, i + 1):
                if 0 <= k < len(turns) and k not in picked:
                    picked.add(k)
            sources.append({"meeting_id": mid, "title": m["title"], "date": h["date"], "kind": "turn",
                            "start_s": h["start_s"], "at": h["at"]})
        for k in sorted(picked):
            n, t, x = turns[k]
            lines.append(f"[{clock(t)}] {n}: {x[:600]}")
        block = "\n".join(lines)
        if used + len(block) > budget:
            block = block[: max(0, budget - used)]
        if block:
            blocks.append(block)
            used += len(block)
        if used >= budget:
            break
    seen, uniq = set(), []
    for s in sources:
        key = (s["meeting_id"], s["kind"], s["start_s"])
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return "\n\n".join(blocks), uniq[:12]


def ask(repo: MeetingRepo, llm: TextLLM, question: str, meeting_id: str | None = None) -> dict[str, Any]:
    hits = search(repo, question, limit=MAX_HITS * 2, meeting_id=meeting_id)
    if not hits:
        return {"answer": "I couldn't find anything about that in your meetings.", "sources": [], "context_chars": 0}
    context, sources = build_context(repo, hits)
    answer = llm(ASK_PROMPT, f"Question: {question}\n\nExcerpts:\n{context}")
    return {"answer": answer, "sources": sources, "context_chars": len(context)}
