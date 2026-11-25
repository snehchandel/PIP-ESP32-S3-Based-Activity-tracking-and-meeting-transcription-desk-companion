"""Meeting summaries on this PC: short meetings in one call, long ones part by part ("map"), then one call that
merges the parts' notes ("reduce").

Why parts: a local 8B model keeps ~8k tokens in view on an 8 GB GPU, which is about half an hour of talk. Each
part is ~12k characters (~3k tokens, ~15 min of talk) and comes back as a few lines of notes (~200 tokens), so
the final call reads a few hundred tokens per part instead of the whole transcript. Parts also make the job
pausable: between two parts the worker can step aside for a new transcription or a voice command, and the notes
already made are kept (`notes` cache), so nothing is redone."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol

from ..planner.schema import MeetingSummary
from .export import clock, speaker_turns

SINGLE_PASS_CHARS = 20_000  # up to ~30 min of talk: one call
CHUNK_CHARS = 12_000        # longer meetings: parts of ~15 min


class JsonLLM(Protocol):
    def chat_json(self, system: str, user: str, schema: dict[str, Any], purpose: str,
                  max_out: int = 1200) -> dict[str, Any]: ...


class Yielded(Exception):  # noqa: N818 - control flow, not an error
    """Raised between two parts when more urgent work is waiting; the notes made so far are kept."""


_STR = {"type": "string"}
_ACTIONS = {"type": "array", "items": {"type": "object", "properties": {
    "task": _STR, "owner": {"type": ["string", "null"]}, "due": {"type": ["string", "null"]}},
    "required": ["task", "owner", "due"]}}
_LIST = {"type": "array", "items": _STR}
NOTES_SCHEMA = {"type": "object", "properties": {"points": _LIST, "decisions": _LIST, "action_items": _ACTIONS,
                                                 "topics": _LIST},
                "required": ["points", "decisions", "action_items", "topics"]}
SUMMARY_SCHEMA = {"type": "object", "properties": {"title": _STR, "summary": _STR, "decisions": _LIST,
                                                   "action_items": _ACTIONS, "topics": _LIST},
                  "required": ["title", "summary", "decisions", "action_items", "topics"]}

RULES = """Rules: use only what was actually said; use the speaker names as written; no markdown, no emojis.
An action item is a concrete next action someone agreed to do ("I'll send...", "can you book..."): owner = that
person's name if known, else null; due = the deadline as said ("Friday", "next week"), else null.
Topics are 2-6 short noun phrases naming the subjects discussed (e.g. "Q3 budget", "hiring plan") - not people."""

SUMMARY_PROMPT = """You summarise meeting transcripts for an ADHD-friendly assistant. Lines are
"[mm:ss] Speaker: words". Reply with JSON: title (what the meeting was about, max 60 chars), summary (3-6 plain
sentences: purpose, what was discussed, outcome), decisions, action_items, topics.
""" + RULES

PART_PROMPT = """You take notes on part {i} of {n} of a meeting transcript. Lines are "[mm:ss] Speaker: words".
Reply with JSON: points (at most 6 short sentences, each with the [mm:ss] where it was said), decisions,
action_items, topics. Leave a list empty when the part has nothing for it.
""" + RULES

MERGE_PROMPT = """You get the notes of every part of one meeting, in order. Write the meeting's summary as JSON:
title (what the meeting was about, max 60 chars), summary (3-6 plain sentences: purpose, what was discussed,
outcome), decisions, action_items, topics. Merge duplicates; a later part overrides an earlier one when
they disagree (a changed decision, a moved deadline).
""" + RULES


def transcript_lines(meeting: dict[str, Any], segments: list[dict[str, Any]]) -> list[str]:
    """Compact "[mm:ss] Name: text" lines, one per speaker turn - the cheapest form that still says who and when."""
    names = {sp["key"]: sp["name"] for sp in meeting.get("speakers", [])}
    return [f"[{clock(t)}] {name}: {text}" for name, t, text in speaker_turns(segments, names)]


def chunks(lines: list[str], size: int = CHUNK_CHARS) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    n = 0
    for line in lines:
        if cur and n + len(line) > size:
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(line[: size])  # one monologue longer than a part is cut, not dropped
        n += len(cur[-1]) + 1
    if cur:
        out.append("\n".join(cur))
    return out


def _s(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def clean(data: dict[str, Any], fallback_title: str) -> dict[str, Any]:
    """Whatever the model returned -> a valid MeetingSummary dict (trimmed, de-duplicated, no empties)."""
    def uniq(items: list[str], n: int, limit: int) -> list[str]:
        seen: dict[str, str] = {}
        for it in items:
            s = _s(it, n)
            if len(s) >= 2 and s.lower() not in seen:
                seen[s.lower()] = s
        return list(seen.values())[:limit]

    actions, seen = [], set()
    for a in data.get("action_items") or []:
        if not isinstance(a, dict):
            continue
        task = _s(a.get("task"), 200)
        if len(task) < 2 or task.lower() in seen:
            continue
        seen.add(task.lower())
        owner, due = _s(a.get("owner"), 60), _s(a.get("due"), 60)
        actions.append({"task": task, "owner": owner if owner.lower() not in ("", "null", "none") else None,
                        "due": due if due.lower() not in ("", "null", "none") else None})
    topics = uniq([str(t).strip("#[] ") for t in data.get("topics") or []], 40, 8)
    title = _s(data.get("title"), 80)
    summary = _s(data.get("summary"), 2000)
    out = {"title": title if len(title) >= 2 else fallback_title[:80] or "Meeting",
           "summary": summary if len(summary) >= 2 else "No summary could be made from this transcript.",
           "decisions": uniq([str(d) for d in data.get("decisions") or []], 300, 20),
           "action_items": actions[:30], "topics": [t for t in topics if len(t) >= 2]}
    return MeetingSummary.model_validate(out).model_dump()


def _notes_text(i: int, n: int, part: str, notes: dict[str, Any]) -> str:
    first = re.match(r"\[([\d:]+)\]", part)
    last = re.findall(r"^\[([\d:]+)\]", part, re.M)
    span = f" ({first.group(1)}-{last[-1]})" if first and last else ""
    lines = [f"Part {i}/{n}{span}:"]
    lines += [f"- {_s(p, 300)}" for p in notes.get("points") or []]
    if notes.get("decisions"):
        lines.append("Decisions: " + "; ".join(_s(d, 200) for d in notes["decisions"]))
    for a in notes.get("action_items") or []:
        if isinstance(a, dict) and a.get("task"):
            extra = ", ".join(x for x in (_s(a.get("owner"), 60), _s(a.get("due"), 60)) if x and x != "null")
            lines.append(f"Action: {_s(a['task'], 200)}" + (f" ({extra})" if extra else ""))
    if notes.get("topics"):
        lines.append("Topics: " + ", ".join(_s(t, 40) for t in notes["topics"]))
    return "\n".join(lines)


def summarize(llm: JsonLLM, meeting: dict[str, Any], segments: list[dict[str, Any]], context: str = "",
              notes: dict[int, dict[str, Any]] | None = None, should_yield: Callable[[], bool] | None = None,
              on_progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """The meeting's summary dict (MeetingSummary + topics). `notes` caches finished parts across a Yielded."""
    lines = transcript_lines(meeting, segments)
    if not lines:
        raise ValueError("this meeting has no transcript yet")
    head = f"Meeting: {meeting.get('title', '')}\n{context}".strip() + "\n\n"
    text = "\n".join(lines)
    if len(text) <= SINGLE_PASS_CHARS:
        if on_progress:
            on_progress(0, 1)
        out = clean(llm.chat_json(SUMMARY_PROMPT, head + text, SUMMARY_SCHEMA, "meeting_summary"),
                    meeting.get("title", ""))
        if on_progress:
            on_progress(1, 1)
        return out
    parts = chunks(lines)
    notes = notes if notes is not None else {}
    for i, part in enumerate(parts):
        if i in notes:
            continue
        if should_yield and should_yield():
            raise Yielded
        if on_progress:
            on_progress(i, len(parts) + 1)
        notes[i] = llm.chat_json(PART_PROMPT.format(i=i + 1, n=len(parts)), head + part, NOTES_SCHEMA,
                                 "meeting_notes", max_out=700)
    if should_yield and should_yield():
        raise Yielded
    if on_progress:
        on_progress(len(parts), len(parts) + 1)
    merged = "\n\n".join(_notes_text(i + 1, len(parts), parts[i], notes[i]) for i in range(len(parts)))
    out = clean(llm.chat_json(MERGE_PROMPT, head + merged, SUMMARY_SCHEMA, "meeting_summary"), meeting.get("title", ""))
    if on_progress:
        on_progress(len(parts) + 1, len(parts) + 1)
    return out
