"""What happens to a meeting's action items after the summary (ADR-032).

A meeting produces commitments for several people. For an ADHD-friendly planner the useful questions are "which of
these are MINE, and when?", not "park everything". So every action item gets:
- `mine`: the owner is the user (Settings -> Meetings -> "Your name"; guessed from the voice that appears in most
  meetings). Unowned items count as possibly mine.
- `due_date` / `due_time` / `due_exact`: the deadline words resolved against the meeting's date (due.py). The user
  can correct the date; a corrected date is never overwritten by a re-summary.
- `status`: new -> task (a scheduled task on that date) | reminder (a ping at that date/time) | parked (a parked
  tangent, no date) | dismissed (not for me / not needed). `ref_id` points at what was made.

Dated items that are still `new` show on the Calendar ("from meeting", dashed) until the user decides; the user's own
and unowned ones by default, other people's on request - they are their tasks, but a reminder to follow up on them
can be made from the same item. Nothing is created without the user choosing it."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .due import resolve_due

STATUSES = ("new", "task", "reminder", "parked", "dismissed")


def meeting_day(meeting: dict[str, Any]) -> date:
    dt = datetime.fromisoformat(str(meeting["started_at"]).replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo(meeting.get("timezone") or "UTC")).date()


def is_mine(owner: str | None, my_name: str) -> bool:
    if not my_name or not owner:
        return False
    names = {n.strip().lower() for n in re.split(r",|&|\band\b|/", owner) if n.strip()}
    me = my_name.strip().lower()
    return me in names or any(n.split()[0] == me.split()[0] for n in names if n)


def enrich(summary: dict[str, Any], meeting: dict[str, Any], my_name: str) -> dict[str, Any]:
    """Fill due dates (unless the user set one), `mine` and defaults on every action item, in place."""
    day = meeting_day(meeting)
    for a in summary.get("action_items") or []:
        a.setdefault("status", "parked" if a.get("parked") else "new")
        if not a.get("due_user"):
            d = resolve_due(a.get("due"), day)
            a["due_date"] = d.day.isoformat() if d else None
            a["due_time"] = d.at.strftime("%H:%M") if d and d.at else None
            a["due_exact"] = bool(d.exact) if d else True
        a["mine"] = is_mine(a.get("owner"), my_name)
    return summary


def guess_my_name(meetings: list[dict[str, Any]]) -> str:
    """The named speaker present in the most meetings (the person who owns PIP records most of them)."""
    count: dict[str, int] = {}
    for m in meetings:
        for sp in m.get("speakers") or []:
            name = str(sp.get("name") or "")
            if name and not re.fullmatch(r"Speaker \d+", name):
                count[name] = count.get(name, 0) + 1
    best = sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))
    return best[0][0] if best and (len(best) == 1 or best[0][1] > best[1][1]) else ""


def calendar_items(meetings: list[dict[str, Any]], start: date, days: int, include_others: bool) -> dict[str, list[dict[str, Any]]]:
    """Undecided dated action items per day (kind 3 on the Calendar)."""
    end = start + timedelta(days=days)
    out: dict[str, list[dict[str, Any]]] = {}
    for m in meetings:
        if m.get("archived"):
            continue
        for i, a in enumerate((m.get("summary") or {}).get("action_items") or []):
            if a.get("status", "new") != "new" or a.get("done") or not a.get("due_date"):
                continue
            mine_or_open = a.get("mine") or not a.get("owner")
            if not (mine_or_open or include_others):
                continue
            d = date.fromisoformat(a["due_date"])
            if not start <= d < end:
                continue
            out.setdefault(d.isoformat(), []).append({
                "id": f"{m['id']}:{i}", "title": a["task"], "hhmm": a.get("due_time") or "", "kind": 3,
                "done": False, "active": False, "duration_min": 15, "meeting_id": m["id"], "meeting": m["title"],
                "index": i, "owner": a.get("owner"), "mine": bool(a.get("mine")), "exact": a.get("due_exact", True)})
    return out
