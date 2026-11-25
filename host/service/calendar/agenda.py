"""Builds the device CALENDAR_SYNC payload and the desktop Today/Tomorrow/calendar views."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..alarms.schedule import upcoming


def _local_day(utc_iso: str, tz: ZoneInfo) -> tuple[date, str]:
    dt = datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone(tz)
    return dt.date(), dt.strftime("%H:%M")


def day_items(tasks: list[dict[str, Any]], reminders: list[dict[str, Any]], alarms: list[dict[str, Any]],
              day: date, tz: ZoneInfo) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for t in tasks:
        if t["target_date"] == day.isoformat() and t["status"] != "ARCHIVED":
            steps = t.get("steps") or []
            minutes = t.get("block_min") or sum(s["duration_min"] for s in steps if s["status"] != "COMPLETED") or \
                sum(s["duration_min"] for s in steps) or 30
            items.append({"id": t["id"], "title": t["title"], "hhmm": t.get("start_hhmm") or "", "kind": 0,
                          "done": t["status"] == "COMPLETED", "active": t["status"] == "ACTIVE",
                          "duration_min": minutes})
    for r in reminders:
        d, hhmm = _local_day(r["due_utc"], tz)
        if d == day:
            items.append({"id": r["id"], "title": r["title"], "hhmm": hhmm, "kind": 1, "done": bool(r["done"]),
                          "active": False, "duration_min": 15})
    weekday = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][day.weekday()]
    for a in alarms:
        if not a.get("enabled"):
            continue
        if a.get("schedule_kind") == "ONCE" and a.get("fire_utc"):
            d, hhmm = _local_day(a["fire_utc"], tz)
            if d != day:
                continue
        elif a.get("schedule_kind") == "RECURRING" and weekday in (a.get("rrule_days") or "").split(","):
            hhmm = a["local_hhmm"]
        else:
            continue
        items.append({"id": a["id"], "title": a["title"], "hhmm": hhmm, "kind": 2, "done": False,
                      "active": False, "duration_min": 10, "recurring": a.get("schedule_kind") == "RECURRING"})
    # active first, then timed items by time, then the rest; done items sink
    return sorted(items, key=lambda i: (i["done"], not i["active"], i["hhmm"] or "99:99"))


def upcoming_items(tasks: list[dict[str, Any]], reminders: list[dict[str, Any]], alarms: list[dict[str, Any]],
                   today: date, tz: ZoneInfo, days: int = 7, limit: int = 6) -> list[dict[str, Any]]:
    """Open items after today (the next week), soonest first, for the device board's "Coming up" list."""
    out: list[dict[str, Any]] = []
    for k in range(1, days + 1):
        day = today + timedelta(days=k)
        for i in day_items(tasks, reminders, alarms, day, tz):
            if i["done"]:
                continue
            out.append({"day": day.strftime("%a"), "hhmm": i["hhmm"], "title": i["title"][:39], "kind": i["kind"]})
            if len(out) >= limit:
                return out
    return out


def calendar_sync(tasks: list[dict[str, Any]], reminders: list[dict[str, Any]], alarms: list[dict[str, Any]],
                  parked_count: int, tz: ZoneInfo, rev: int) -> dict[str, Any]:
    today = datetime.now(tz).date()
    t_items = day_items(tasks, reminders, alarms, today, tz)
    tomorrow = day_items(tasks, reminders, alarms, today + timedelta(days=1), tz)
    return {
        "upcoming": upcoming_items(tasks, reminders, alarms, today, tz),
        "rev": rev,
        "date_label": today.strftime("%a, %b ") + str(today.day),
        "today": [{"id": i["id"][:23], "title": i["title"][:39], "hhmm": i["hhmm"], "kind": i["kind"],
                   "done": i["done"]} for i in t_items[:8]],
        "tomorrow_count": len(tomorrow),
        "parked_count": parked_count,
        "upcoming_alarms": upcoming(alarms, tz),
    }
