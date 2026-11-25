"""Meeting transcript exports: Markdown, plain text, SubRip subtitles (.srt) and JSON."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

FORMATS = {"md": "text/markdown", "txt": "text/plain", "srt": "application/x-subrip", "json": "application/json"}


def clock(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _local(utc_iso: str | None, tz: str) -> datetime | None:
    if not utc_iso:
        return None
    dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(ZoneInfo(tz))


def when(meeting: dict[str, Any]) -> str:
    start = _local(meeting.get("started_at"), meeting["timezone"])
    end = _local(meeting.get("ended_at"), meeting["timezone"])
    if start is None:
        return ""
    out = start.strftime("%A, %B ") + str(start.day) + start.strftime(", %Y · %H:%M")
    if end is not None:
        out += end.strftime("–%H:%M")
    return out + f" ({meeting['timezone']})"


def filename(meeting: dict[str, Any], ext: str) -> str:
    start = _local(meeting.get("started_at"), meeting["timezone"])
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", meeting["title"]).strip().replace(" ", "_")[:60] or "meeting"
    return f"{start.strftime('%Y-%m-%d_%H%M') + '_' if start else ''}{stem}.{ext}"


def _turns(segments: list[dict[str, Any]], names: dict[str, str]) -> list[tuple[str, float, str]]:
    """Consecutive segments of one speaker joined into a turn: (name, start, text)."""
    turns: list[tuple[str, float, str]] = []
    for s in segments:
        name = names.get(s["speaker_key"], s["speaker_key"])
        if turns and turns[-1][0] == name:
            turns[-1] = (name, turns[-1][1], f"{turns[-1][2]} {s['text']}")
        else:
            turns.append((name, s["start_s"], s["text"]))
    return turns


def render(meeting: dict[str, Any], segments: list[dict[str, Any]], fmt: str) -> str:
    names = {sp["key"]: sp["name"] for sp in meeting.get("speakers", [])}
    summary = meeting.get("summary") or None
    if fmt == "json":
        return json.dumps({
            "title": meeting["title"], "started_at": meeting["started_at"], "ended_at": meeting.get("ended_at"),
            "timezone": meeting["timezone"], "duration_s": meeting["duration_s"],
            "speakers": [{"key": k, "name": v} for k, v in names.items()],
            "notes": meeting.get("notes") or "", "summary": summary,
            "segments": [{"start_s": round(s["start_s"], 2), "end_s": round(s["end_s"], 2),
                          "speaker": names.get(s["speaker_key"], s["speaker_key"]), "text": s["text"]}
                         for s in segments],
        }, indent=2, ensure_ascii=False)
    if fmt == "srt":
        return "\n".join(f"{i}\n{_srt_time(s['start_s'])} --> {_srt_time(s['end_s'])}\n"
                         f"{names.get(s['speaker_key'], s['speaker_key'])}: {s['text']}\n"
                         for i, s in enumerate(segments, 1))
    who = ", ".join(names.values()) or "-"
    dur = clock(meeting["duration_s"])
    if fmt == "txt":
        lines = [meeting["title"], when(meeting), f"Duration: {dur}", f"Speakers: {who}", ""]
        if meeting.get("notes"):
            lines += ["Notes:", meeting["notes"], ""]
        if summary:
            lines += ["Summary:", summary.get("summary", ""), ""]
            lines += [f"Decision: {d}" for d in summary.get("decisions", [])]
            lines += [f"Action: {a.get('task', '')}" + (f" ({a['owner']})" if a.get("owner") else "")
                      + (f" - due {a['due']}" if a.get("due") else "") for a in summary.get("action_items", [])]
            lines.append("")
        lines += [f"[{clock(t)}] {name}: {text}" for name, t, text in _turns(segments, names)]
        return "\n".join(lines) + "\n"
    # markdown
    md = [f"# {meeting['title']}", "", f"**When:** {when(meeting)}  ", f"**Duration:** {dur}  ",
          f"**Speakers:** {who}", ""]
    if meeting.get("notes"):
        md += ["## Notes", "", meeting["notes"], ""]
    if summary:
        md += ["## Summary", "", summary.get("summary", ""), ""]
        if summary.get("decisions"):
            md += ["### Decisions", "", *[f"- {d}" for d in summary["decisions"]], ""]
        if summary.get("action_items"):
            md += ["### Action items", "", *[f"- [ ] {a.get('task', '')}" + (f" — {a['owner']}" if a.get("owner") else "")
                                              + (f" (due {a['due']})" if a.get("due") else "")
                                              for a in summary["action_items"]], ""]
    md += ["## Transcript", ""]
    md += [f"**{name}** `{clock(t)}`  \n{text}\n" for name, t, text in _turns(segments, names)]
    return "\n".join(md)
