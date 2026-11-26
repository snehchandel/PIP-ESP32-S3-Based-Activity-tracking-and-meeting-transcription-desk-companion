"""Summaries by another AI agent (ADR-036): the transcript and a prompt go out as Markdown, the agent's summary comes
back as Markdown and becomes the meeting's summary, exactly as if PIP had made it (action items, calendar, Obsidian).

Out: `handoff_md()` = the prompt + the transcript in one .md file (export format "ai"), or `PROMPT` alone for the
user to paste next to the ordinary Markdown export. In: `parse_summary_md()` reads what the agent wrote. Agents
rarely follow a format to the letter, so the reader is lenient: any heading level or a bold label for a section,
synonyms ("Next steps" = action items), checkboxes or plain bullets, "Owner:"/"Due:" in any order and separator,
timestamps with or without brackets, a fenced reply, YAML front matter, or a JSON object instead of Markdown.
`summarize.clean()` then tidies the result like any other summary."""
from __future__ import annotations

import json
import re
from typing import Any

from .export import clock, speaker_turns, when
from .summarize import DEFINITIONS

FORMAT = """# <what the meeting was about, at most 60 characters>

## Outcome
<1-2 sentences: how the meeting ended - what the speakers concluded or agreed by the end>

## Summary
<4-7 plain sentences: why they met, the main threads with who said what, the decisions and next steps, the outcome>

## Key points
- [mm:ss] <who said or concluded what, with specifics: systems, numbers, dates, names>

## Topics
- <3-7 short noun phrases naming the main subjects - not people>

## Decisions
- <one agreed decision per line>

## Action items
- [ ] [mm:ss] <task starting with a verb> | Owner: <name or none> | Due: <deadline words as said, or none>"""

PROMPT = f"""You are an expert meeting analyst. The attached Markdown file is the transcript of one meeting, made by
speech recognition. Transcript lines look like "[mm:ss] Speaker: words" (the speaker name may be in **bold**). If the
file already contains a summary, ignore it: work only from the transcript lines.

Write the meeting summary in EXACTLY this Markdown format (keep the headings in English and in this order; write
"- none" under a heading that has nothing):

{FORMAT}

Rules:
- Key points: 8-14 points spread over the WHOLE meeting, start to end, in order, each starting with the [mm:ss] of
  the line it comes from.
- Action items: one per line, each with the [mm:ss] where it was said, then "| Owner: ..." and "| Due: ...".
{DEFINITIONS.removesuffix("No markdown, no emojis.").rstrip()}
Reply with the Markdown summary only - no introduction, no closing remarks. I will upload it into my meeting app,
which reads these headings."""


def handoff_md(meeting: dict[str, Any], segments: list[dict[str, Any]], vocabulary: list[str] | None = None) -> str:
    """One file to give another AI agent: the prompt, then the meeting's facts and every speaker turn."""
    names = {sp["key"]: sp["name"] for sp in meeting.get("speakers", [])}
    facts = [f"- When: {when(meeting)}", f"- Duration: {clock(meeting.get('duration_s', 0))}"]
    if names:
        facts.append(f"- Speakers: {', '.join(names.values())}")
    if vocabulary:
        facts.append(f"- Spellings of names and terms: {', '.join(vocabulary)}")
    md = ["# Instructions for the AI", "", PROMPT, "", "---", "", f"# Transcript: {meeting['title']}", "", *facts, ""]
    if (meeting.get("notes") or "").strip():
        md += ["## Notes taken during the meeting", "", meeting["notes"].strip(), ""]
    md += ["## Transcript", "", *[f"[{clock(t)}] **{n}**: {x}\n" for n, t, x in speaker_turns(segments, names)]]
    return "\n".join(md).rstrip() + "\n"


# ---- reading the agent's reply --------------------------------------------------------------------------------
_SECTIONS: list[tuple[str, re.Pattern[str]]] = [  # first match wins: "action items" before "summary", etc.
    ("action_items", re.compile(r"\baction|\bnext steps?\b|\bto-?dos?\b|\btasks?\b|\bfollow[- ]?ups?\b|\bcommitments?\b")),
    ("decisions", re.compile(r"\bdecisions?\b|\bdecided\b|\bagreements?\b|\bagreed\b")),
    ("key_points", re.compile(r"\bkey points?\b|\bhighlights?\b|\bdiscussion\b|\bkey takeaways?\b|\btakeaways?\b|"
                              r"\btimeline\b|\bnotes\b|\bdetails\b")),
    ("topics", re.compile(r"\btopics?\b|\bthemes?\b|\bsubjects?\b|\btags?\b")),
    ("outcome", re.compile(r"\boutcomes?\b|\bconclusions?\b|\bresults?\b|\bbottom line\b")),
    ("summary", re.compile(r"\bsummary\b|\boverview\b|\btl;? ?dr\b|\bsynopsis\b|\brecap\b|\babstract\b")),
    ("title", re.compile(r"^(?:meeting )?title$")),
]
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LABEL = re.compile(r"^(?:\*\*|__)([^*_]{2,40}?)(:?)(?:\*\*|__)(:?)\s*(.*)$")  # **Summary:** text
_PLAIN_LABEL = re.compile(r"^([A-Za-z][A-Za-z ;/&-]{1,30})(:)()\s*(.*)$")    # Summary: text
_FIELD = re.compile(r"^(?:owner|who|assignee|assigned to|due|deadline|by when)\s*:", re.I)
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+(.*)$")
_BOX = re.compile(r"^\[( |x|X)\]\s*")
_STAMP = re.compile(r"^[\[(]?(\d{1,2}:\d{2}(?::\d{2})?)[\])]?\s*[-–—:,]?\s*")
_FIELD_STOP = r"(?=\s*(?:\||;|\s[-–—]\s|\(|\)|,?\s*\b(?:owner|who|assignee|assigned to|due|deadline|by when)\s*:|$))"
_OWNER = re.compile(r"\b(?:owner|who|assignee|assigned to)\s*:\s*(.*?)" + _FIELD_STOP, re.I)
_DUE = re.compile(r"\b(?:due|deadline|by when)\s*:\s*(.*?)" + _FIELD_STOP, re.I)
_GENERIC_TITLE = re.compile(r"^(?:meeting\s+)?(?:summary|notes|minutes|recap)(?:\s+of\s+the\s+meeting)?$", re.I)
_TITLE_PREFIX = re.compile(r"^(?:meeting\s+)?(?:summary|notes|minutes|recap)\s*(?:[:–—-]|of)\s*", re.I)
_NONE = {"none", "- none", "n/a", "nothing", "no action items", "no decisions", "none.", "-"}


def _inline(s: str) -> str:
    """Markdown emphasis, code, wiki links and links -> plain text (keeps "[12:34]" stamps)."""
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)   # [[note|text]] -> text
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)             # [text](url) -> text
    s = re.sub(r"(\*\*|__|`)", "", s)
    s = re.sub(r"(?<![\w*])[*_]([^*_]+)[*_](?![\w*])", r"\1", s)  # *text* / _text_
    return " ".join(s.split())


def _section(name: str) -> str | None:
    key = re.sub(r"[^a-z0-9 ;/&-]+", " ", _inline(name).lower()).strip()
    key = " ".join(key.split())
    for section, pat in _SECTIONS:
        if pat.search(key):
            return section
    return None


def _stamped(item: str) -> tuple[str | None, str]:
    m = _STAMP.match(item)
    return (m.group(1), item[m.end():].strip()) if m else (None, item)


def _action(item: str) -> dict[str, Any]:
    item = _BOX.sub("", item)
    at, rest = _stamped(item)
    owner = _OWNER.search(rest)
    due = _DUE.search(rest)
    task = rest
    for m in sorted((x for x in (owner, due) if x), key=lambda x: x.start(), reverse=True):
        task = task[:m.start()] + task[m.end():]
    task = re.sub(r"\(\s*[,;]?\s*\)", "", task)               # "(Owner: X, Due: Y)" leaves "( , )"
    task = re.sub(r"\s*(?:\||;|\s[-–—]\s)\s*(?=\||;|$)", "", task)
    task = re.sub(r"[\s|;,–—-]+$", "", task).strip()
    if at is None:  # "Send the deck (12:34)" / "Send the deck [at 12:34]"
        tail = re.search(r"\s*[\[(](?:at\s+)?(\d{1,2}:\d{2}(?::\d{2})?)[\])]\s*$", task)
        if tail:
            at, task = tail.group(1), task[:tail.start()].strip()
    return {"task": task, "said_at": at, "owner": owner.group(1).strip(" .") if owner else None,
            "due": due.group(1).strip(" .") if due else None}


def _from_json(text: str) -> dict[str, Any] | None:
    body = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    if not body.startswith(("{", "[")):
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    return data if isinstance(data, dict) and (data.get("summary") or data.get("key_points")) else None


def parse_summary_md(text: str) -> dict[str, Any]:
    """The agent's summary (Markdown, or JSON) -> the raw fields `summarize.clean()` expects. Raises ValueError when
    nothing in it looks like a meeting summary."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").strip()
    data = _from_json(text)
    if data is not None:
        return data
    fence = re.fullmatch(r"```[a-zA-Z]*\n(.*?)\n?```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    title = ""
    front = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if front:
        t = re.search(r"^title:\s*[\"']?(.*?)[\"']?\s*$", front.group(1), re.M)
        title = t.group(1).strip() if t else ""
        text = text[front.end():]
    parts: dict[str, list[str]] = {}
    cur: str | None = None
    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip() or re.fullmatch(r"\s*(?:---+|\*\*\*+|___+)\s*", line):
            if cur and parts.get(cur) and parts[cur][-1] != "":
                parts[cur].append("")  # paragraph break
            continue
        h = _HEADING.match(line.strip())
        if h:
            name = _inline(h.group(2))
            section = _section(name)
            if len(h.group(1)) == 1 and section in (None, "summary", "title"):
                if not title and not _GENERIC_TITLE.match(name):
                    title = _TITLE_PREFIX.sub("", name).strip()
                cur = "summary" if section == "summary" and _GENERIC_TITLE.match(name) else None
                continue
            cur = section or "_other"
            continue
        lab = _LABEL.match(line.strip()) or (_PLAIN_LABEL.match(line.strip()) if not _BULLET.match(line) else None)
        is_label = bool(lab) and bool(lab.group(2) or lab.group(3) or not lab.group(4).strip()) \
            and len(lab.group(1).split()) <= 4  # "**Summary:** text", "**Decisions**", "Next steps:"
        if lab and is_label and _section(lab.group(1)):
            cur = _section(lab.group(1))
            named = _TITLE_PREFIX.sub("", _inline(lab.group(1))).strip()
            if cur == "summary" and not title and named and named != _inline(lab.group(1)):
                title = named  # "**Meeting summary: Vendor call**"
            if lab.group(4).strip():
                parts.setdefault(cur or "_other", []).append(lab.group(4).strip())
            continue
        if cur:
            parts.setdefault(cur, []).append(line)
    if "title" in parts and not title:
        title = _inline(" ".join(x for x in parts.pop("title") if x))

    def items(key: str) -> list[str]:
        out: list[str] = []
        for line in parts.get(key, []):
            if not line:
                continue
            b = _BULLET.match(line)
            nested = bool(out) and line.startswith((" ", "\t"))
            body = b.group(1) if b else line.strip()
            if nested and _FIELD.match(_inline(body)):
                out[-1] += " | " + body  # "  - Owner: Sam" under its action item
            elif b:
                out.append(body)
            elif nested:
                out[-1] += " " + body  # a wrapped bullet
            else:
                out.append(body)
        out = [_inline(x) for x in out]
        return [x for x in out if x and x.lower().strip(" .") not in _NONE]

    def prose(key: str) -> str:
        return _inline(" ".join(re.sub(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+", "", x) for x in parts.get(key, []) if x))

    topics = items("topics")
    if len(topics) == 1 and "," in topics[0]:
        topics = [t.strip() for t in topics[0].split(",")]
    key_points = []
    for k in items("key_points"):
        at, rest = _stamped(k)
        key_points.append(f"[{at}] {rest}" if at else k)
    actions = [_action(a) for a in items("action_items")]
    decisions = [_stamped(_BOX.sub("", d))[1] for d in items("decisions")]
    summary, outcome = prose("summary"), prose("outcome")
    if not (summary or key_points or actions or decisions):
        raise ValueError("this doesn't look like a meeting summary - expected headings such as "
                         "'## Summary', '## Key points' and '## Action items'")
    if not summary:
        summary = outcome or " ".join(_stamped(k)[1] for k in key_points[:4])
    return {"title": title, "summary": summary, "outcome": outcome, "key_points": key_points,
            "topics": [t.strip("#") for t in topics], "decisions": decisions, "action_items": actions}
