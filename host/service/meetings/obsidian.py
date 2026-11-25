"""Meetings as Obsidian notes, written straight into the user's vault (Settings -> Meetings -> Obsidian vault).

Layout (inside the vault, folder "PIP Meetings" by default):
  2026-11-25 1432 Weekly sync.md                  the meeting: frontmatter, summary, decisions, action items
  Transcripts/2026-11-25 1432 Weekly sync (transcript).md   every line, "[mm:ss] **Name**: words"
  Meetings index.md                                one row per meeting: date, people, topics, open actions, gist
  Action items.md                                  every action item, open first, linked to its meeting
  _About these notes.md                            how the folder is organised (for people and AI assistants)

Links make the graph: people become [[Ana]] (named speakers only - "Speaker 01" is not a person), the day becomes
[[2026-11-25]] (Obsidian's daily note), topics from the summary and the user's own vocabulary become [[Q3 budget]].

The summary note is small on purpose: an assistant answering a question reads the index (one line per meeting),
then the few meeting notes that matter, and opens a transcript only for the exact wording - far fewer tokens than
reading transcripts. PIP rewrites only what it generated: everything under the "My notes" marker is the user's,
and action items ticked in Obsidian stay ticked (and are read back into PIP as done)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .export import _local, clock, speaker_turns

DEFAULT_FOLDER = "PIP Meetings"
MARK = "%% PIP: everything below this line is yours - PIP never changes it %%"
_BAD = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]+')
_DEFAULT_SPEAKER = re.compile(r"Speaker \d+")
_TASK = re.compile(r"^- \[([ xX])\] (.+)$")


def safe_name(s: str, n: int = 80) -> str:
    """A file name / link target Obsidian and Windows both accept."""
    out = " ".join(_BAD.sub(" ", s).split())[:n].strip(" .")
    return out or "Untitled"


def link(name: str) -> str:
    target = safe_name(name, 60)
    shown = name.replace("|", "/").replace("]", ")").replace("[", "(")
    return f"[[{target}]]" if target == shown else f"[[{target}|{shown}]]"


def is_person(name: str) -> bool:
    return bool(name.strip()) and not _DEFAULT_SPEAKER.fullmatch(name.strip())


def q(s: Any) -> str:
    """A YAML scalar: JSON strings are valid double-quoted YAML."""
    return json.dumps(s, ensure_ascii=False)


def note_stem(meeting: dict[str, Any]) -> str:
    start = _local(meeting.get("started_at"), meeting["timezone"])
    return safe_name(f"{start.strftime('%Y-%m-%d %H%M') + ' ' if start else ''}{meeting['title']}", 90)


def topics_for(meeting: dict[str, Any], segments: list[dict[str, Any]], vocabulary: list[str]) -> list[str]:
    """The summary's topics, plus the user's own vocabulary words that come up in the meeting (not people)."""
    people = {sp["name"].lower() for sp in meeting.get("speakers", [])}
    out: dict[str, str] = {}
    for t in (meeting.get("summary") or {}).get("topics") or []:
        if t.lower() not in people:
            out.setdefault(t.lower(), t)
    text = " ".join(s["text"] for s in segments) + " " + json.dumps(meeting.get("summary") or {})
    for w in vocabulary:
        if w.lower() not in people and re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.I):
            out.setdefault(w.lower(), w)
    return list(out.values())[:12]


def _action_line(a: dict[str, Any], done: bool) -> str:
    extra = []
    if a.get("owner"):
        extra.append(link(a["owner"]) if is_person(a["owner"]) else a["owner"])
    if a.get("due"):
        extra.append(f"due {a['due']}")
    return f"- [{'x' if done else ' '}] {a['task']}" + (f" — {', '.join(extra)}" if extra else "")


def render_note(meeting: dict[str, Any], segments: list[dict[str, Any]], vocabulary: list[str],
                transcript: str | None = None, mine: str = "") -> str:
    """The meeting note. `transcript` = stem of the separate transcript note; None puts the transcript inline
    (the single-file Markdown download)."""
    start = _local(meeting.get("started_at"), meeting["timezone"])
    end = _local(meeting.get("ended_at"), meeting["timezone"])
    summary = meeting.get("summary") or {}
    people = [sp["name"] for sp in meeting.get("speakers", []) if is_person(sp["name"])]
    topics = topics_for(meeting, segments, vocabulary)
    actions = summary.get("action_items") or []
    fm = ["---", "type: meeting", f"title: {q(meeting['title'])}"]
    if start:
        fm += [f"date: {start.date().isoformat()}", f"start: {start.strftime('%Y-%m-%dT%H:%M')}"]
    if end:
        fm.append(f"end: {end.strftime('%Y-%m-%dT%H:%M')}")
    fm.append(f"duration_min: {round(meeting.get('duration_s', 0) / 60)}")
    fm += ["attendees:", *[f"  - {q(link(p))}" for p in people]] if people else ["attendees: []"]
    fm += ["topics:", *[f"  - {q(link(t))}" for t in topics]] if topics else ["topics: []"]
    fm += ["tags:", "  - meeting", "  - pip"]
    if summary:
        fm.append(f"summary_by: {q(meeting.get('summary_engine') or 'unknown')}")
        fm.append(f"open_actions: {sum(1 for a in actions if not a.get('done'))}")
    if transcript:
        fm.append(f"transcript: {q(f'[[{transcript}]]')}")
    fm += [f"pip_id: {meeting['id']}", "---", ""]

    md = [f"# {meeting['title']}", ""]
    facts = []
    if start:
        facts.append(f"[[{start.date().isoformat()}]] {start.strftime('%H:%M')}" + (end.strftime("–%H:%M") if end else ""))
    facts.append(clock(meeting.get("duration_s", 0)))
    if people:
        facts.append("with " + ", ".join(link(p) for p in people))
    md += [" · ".join(facts), ""]
    if topics:
        md += ["Topics: " + ", ".join(link(t) for t in topics), ""]
    if summary:
        md += ["## Summary", "", summary.get("summary", ""), ""]
        if summary.get("decisions"):
            md += ["## Decisions", "", *[f"- {d}" for d in summary["decisions"]], ""]
        if actions:
            md += ["## Action items", "", *[_action_line(a, bool(a.get("done"))) for a in actions], ""]
    elif meeting.get("summary_status") in ("QUEUED", "SUMMARIZING"):
        md += ["## Summary", "", "_Being summarised on this PC..._", ""]
    if meeting.get("notes"):
        md += ["## Notes from the meeting", "", meeting["notes"], ""]
    names = {sp["key"]: sp["name"] for sp in meeting.get("speakers", [])}
    turns = speaker_turns(segments, names)
    if transcript:
        md += ["## Transcript", "", f"[[{transcript}|Full transcript]] ({len(turns)} turns)", ""]
    else:
        md += ["## Transcript", "", *[f"[{clock(t)}] **{n}**: {x}\n" for n, t, x in turns]]
    md += ["## My notes", "", MARK, mine.lstrip("\n") if mine.strip() else ""]
    return "\n".join(fm + md).rstrip() + "\n"


def render_transcript(meeting: dict[str, Any], segments: list[dict[str, Any]], note: str) -> str:
    start = _local(meeting.get("started_at"), meeting["timezone"])
    names = {sp["key"]: sp["name"] for sp in meeting.get("speakers", [])}
    fm = ["---", "type: meeting-transcript", f"meeting: {q(f'[[{note}]]')}"]
    if start:
        fm.append(f"date: {start.date().isoformat()}")
    fm += [f"pip_id: {meeting['id']}", "---", ""]
    body = [f"# {meeting['title']} — transcript", "", f"Back to [[{note}]].", ""]
    body += [f"[{clock(t)}] **{n}**: {x}\n" for n, t, x in speaker_turns(segments, names)]
    return "\n".join(fm + body).rstrip() + "\n"


def _gist(summary: dict[str, Any] | None, n: int = 140) -> str:
    text = " ".join(str((summary or {}).get("summary") or "").split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return (first[: n - 1] + "…" if len(first) > n else first).replace("|", "/")


def render_index(meetings: list[dict[str, Any]], now: datetime) -> str:
    rows = ["| When | Meeting | People | Topics | Open | Gist |", "|---|---|---|---|---|---|"]
    for m in meetings:
        start = _local(m.get("started_at"), m["timezone"])
        stem = Path(m["vault_note"]).stem
        people = ", ".join(sp["name"] for sp in m.get("speakers", []) if is_person(sp["name"]))
        topics = ", ".join((m.get("summary") or {}).get("topics") or [])
        open_n = sum(1 for a in (m.get("summary") or {}).get("action_items") or [] if not a.get("done"))
        title = m["title"].replace("|", "/")
        rows.append(f"| {start.strftime('%Y-%m-%d %H:%M') if start else ''} | [[{stem}\\|{title}]] | "
                    f"{people.replace('|', '/')} | {topics.replace('|', '/')} | {open_n} | {_gist(m.get('summary'))} |")
    return "\n".join(["---", "type: pip-meetings-index", f"updated: {now.strftime('%Y-%m-%dT%H:%M')}", "---", "",
                      "# Meetings", "",
                      "Newest first. Open a meeting for its summary, decisions and action items; the full transcript "
                      "is linked from each meeting. See [[Action items]] for everything still to do.", "", *rows]) + "\n"


def render_actions(meetings: list[dict[str, Any]], now: datetime) -> str:
    open_, done = [], []
    for m in meetings:
        start = _local(m.get("started_at"), m["timezone"])
        ref = f"[[{Path(m['vault_note']).stem}|{m['title'].replace('|', '/').replace(']', ')')}]]"
        day = start.date().isoformat() if start else ""
        for a in (m.get("summary") or {}).get("action_items") or []:
            extra = ", ".join(x for x in (a.get("owner") or "", f"due {a['due']}" if a.get("due") else "") if x)
            line = f"- {a['task']}" + (f" — {extra}" if extra else "") + f" · {ref} ({day})"
            (done if a.get("done") else open_).append(line + (" · parked in PIP" if a.get("parked") else ""))
    return "\n".join(["---", "type: pip-action-items", f"updated: {now.strftime('%Y-%m-%dT%H:%M')}", "---", "",
                      "# Action items from meetings", "",
                      "Tick items in each meeting's note; this list is rebuilt from them.", "",
                      "## Open", "", *(open_ or ["Nothing open."]), "", "## Done", "", *(done or ["Nothing yet."])]) + "\n"


ABOUT = f"""---
type: pip-readme
---
# About these notes

PIP (the desk companion) writes one note per recorded meeting into this folder, after transcribing it and
summarising it on this PC.

How to find things - also the cheapest order for an AI assistant reading this vault:
1. [[Meetings index]]: one line per meeting (when, who, topics, open action items, one-sentence gist).
2. The meeting note: summary, decisions, action items with owners. Frontmatter: `date`, `attendees`, `topics`,
   `open_actions`, `pip_id`, `transcript`.
3. `Transcripts/... (transcript).md` only for exact wording: lines are `[mm:ss] **Name**: words`.
4. [[Action items]]: every action item across meetings, open first.

People are links (`[[Ana]]`) and so are topics and days (`[[2026-11-25]]`), so backlinks show every meeting
with someone or about something. PIP rewrites its own notes when a meeting changes; text under the
"{MARK}" line and ticked action items are kept.
"""


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".pip-tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def read_existing(path: Path) -> tuple[str, set[str]]:
    """(the user's text under the marker, lower-cased action items ticked above it) of an existing note."""
    if not path.exists():
        return "", set()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "", set()
    head, sep, mine = text.partition(MARK)
    ticked = set()
    for line in head.splitlines():
        mt = _TASK.match(line.strip())
        if mt and mt.group(1) in "xX":
            ticked.add(mt.group(2).split(" — ")[0].strip().lower())
    return (mine if sep else ""), ticked


class ObsidianVault:
    def __init__(self, root: Path, folder: str = DEFAULT_FOLDER) -> None:
        self.root = root
        self.folder = safe_name(folder or DEFAULT_FOLDER, 60)

    @property
    def dir(self) -> Path:
        return self.root / self.folder

    def paths(self, meeting: dict[str, Any]) -> tuple[str, str]:
        stem = note_stem(meeting)
        return f"{self.folder}/{stem}.md", f"{self.folder}/Transcripts/{stem} (transcript).md"

    def write_meeting(self, meeting: dict[str, Any], segments: list[dict[str, Any]], vocabulary: list[str]) -> tuple[str, set[str]]:
        """Write (or rewrite) the meeting's note + transcript. Returns (note path relative to the vault, action items
        ticked in Obsidian, lower-cased). A renamed meeting moves its files when the new name is free."""
        rel, rel_t = self.paths(meeting)
        old = meeting.get("vault_note")
        if old and old != rel and (self.root / old).exists() and not (self.root / rel).exists():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            os.replace(self.root / old, self.root / rel)
            old_t = f"{self.folder}/Transcripts/{Path(old).stem} (transcript).md"
            if (self.root / old_t).exists() and not (self.root / rel_t).exists():
                os.replace(self.root / old_t, self.root / rel_t)
        mine, ticked = read_existing(self.root / rel)
        summary = meeting.get("summary") or {}
        for a in summary.get("action_items") or []:
            if a["task"].strip().lower() in ticked:
                a["done"] = True
        _atomic_write(self.root / rel_t, render_transcript(meeting, segments, Path(rel).stem))
        _atomic_write(self.root / rel, render_note(meeting, segments, vocabulary, Path(rel_t).stem, mine))
        return rel, ticked

    def write_overview(self, meetings: list[dict[str, Any]], now: datetime) -> None:
        """meetings: newest first, each with summary, speakers and vault_note."""
        listed = [m for m in meetings if m.get("vault_note")]
        _atomic_write(self.dir / "Meetings index.md", render_index(listed, now))
        _atomic_write(self.dir / "Action items.md", render_actions(listed, now))
        _atomic_write(self.dir / "_About these notes.md", ABOUT)


def detected_vaults() -> list[str]:
    """Vaults Obsidian knows about on this PC (its own obsidian.json), most recently opened first."""
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    cfg = Path(base) / "obsidian" / "obsidian.json"
    try:
        vaults = json.loads(cfg.read_text(encoding="utf-8")).get("vaults") or {}
    except (OSError, ValueError):
        return []
    items = sorted(vaults.values(), key=lambda v: -int(v.get("ts") or 0))
    return [str(v["path"]) for v in items if v.get("path") and Path(str(v["path"])).is_dir()]
