"""Builds the device CALENDAR_SYNC payload and the desktop Today/Tomorrow/calendar views."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..alarms.schedule import upcoming


def _local_day(utc_iso: str, tz: ZoneInfo) -> tuple[date, str]:
    dt = datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(tz)
    return dt.date(), dt.strftime("%H:%M")


def day_items(tasks: list[dict[str, Any]], reminders: list[dict[str, Any]], alarms: list[dict[str, Any]],
              day: date, tz: ZoneInfo) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for t in tasks:
        if t["target_date"] == day.isoformat() and t["status"] != "ARCHIVED":
            items.append({"id": t["id"], "title": t["title"], "hhmm": "", "kind": 0,
                          "done": t["status"] == "COMPLETED", "active": t["status"] == "ACTIVE"})
    for r in reminders:
        d, hhmm = _local_day(r["due_utc"], tz)
        if d == day:
            items.append({"id": r["id"], "title": r["title"], "hhmm": hhmm, "kind": 1, "done": bool(r["done"]),
                          "active": False})
    for a in alarms:
        if a.get("schedule_kind") == "ONCE" and a.get("fire_utc") and a.get("enabled"):
            d, hhmm = _local_day(a["fire_utc"], tz)
            if d == day:
                items.append({"id": a["id"], "title": a["title"], "hhmm": hhmm, "kind": 2, "done": False,
                              "active": False})
    # active first, then timed items by time, then the rest; done items sink
    return sorted(items, key=lambda i: (i["done"], not i["active"], i["hhmm"] or "99:99"))


def calendar_sync(tasks: list[dict[str, Any]], reminders: list[dict[str, Any]], alarms: list[dict[str, Any]],
                  parked_count: int, tz: ZoneInfo, rev: int) -> dict[str, Any]:
    today = datetime.now(tz).date()
    t_items = day_items(tasks, reminders, alarms, today, tz)
    tomorrow = day_items(tasks, reminders, alarms, today + timedelta(days=1), tz)
    return {
        "rev": rev,
        "date_label": today.strftime("%a, %b ") + str(today.day),
        "today": [{"id": i["id"][:23], "title": i["title"][:39], "hhmm": i["hhmm"], "kind": i["kind"],
                   "done": i["done"]} for i in t_items[:4]],
        "tomorrow_count": len(tomorrow),
        "parked_count": parked_count,
        "upcoming_alarms": upcoming(alarms, tz),
    }
