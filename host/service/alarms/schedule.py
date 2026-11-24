"""Alarm occurrence math (one-time + weekly recurring, DST-safe), snooze/dismiss, reboot idempotency."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..calendar.timeparse import resolve_local
from ..storage.repo_alarms import AlarmRepo

DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
MISSED_GRACE = timedelta(minutes=10)


def _utc(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def fmt_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_occurrence(alarm: dict[str, Any], after: datetime) -> datetime | None:
    """Next fire instant strictly after `after` (aware UTC), or None if it will never fire again."""
    if not alarm.get("enabled"):
        return None
    if alarm.get("schedule_kind") == "ONCE":
        t = _utc(alarm.get("fire_utc"))
        return t if t and t > after else None
    tz = ZoneInfo(alarm.get("timezone") or "UTC")
    days = [d for d in (alarm.get("rrule_days") or "").split(",") if d in DAYS]
    if not days:
        return None
    hh, mm = (int(x) for x in alarm["local_hhmm"].split(":"))
    start: date = after.astimezone(tz).date()
    for i in range(0, 8):
        d = start + timedelta(days=i)
        if DAYS[d.weekday()] not in days:
            continue
        local, _ = resolve_local(d, time(hh, mm), tz)
        inst = local.astimezone(UTC)
        if inst > after:
            return inst
    return None


def due_alarms(alarms: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Alarms whose occurrence passed since they last fired (missed > grace are skipped, not rung late)."""
    out = []
    for a in alarms:
        if not a.get("enabled") or a.get("ack_state") == "RINGING":
            continue
        if a.get("ack_state") == "SNOOZED" and a.get("fire_utc"):
            occ = _utc(a["fire_utc"])
        else:
            last = _utc(a.get("last_fired_utc"))
            occ = next_occurrence(a, last or (now - MISSED_GRACE))
        if occ is not None and occ <= now:
            a = dict(a)
            a["_occurrence"] = occ
            a["_late"] = now - occ > MISSED_GRACE
            out.append(a)
    return out


def apply_ack(repo: AlarmRepo, alarm_id: str, snooze: bool) -> None:
    a = repo.get(alarm_id)
    if a is None:
        return
    now = datetime.now(UTC)
    if snooze:
        when = now + timedelta(minutes=int(a.get("snooze_min") or 5))
        if a["schedule_kind"] == "ONCE":
            repo.update(alarm_id, fire_utc=fmt_utc(when), ack_state="SNOOZED", last_fired_utc=fmt_utc(now))
        else:  # recurring: one-shot snooze via a fire_utc override consumed by the scheduler
            repo.update(alarm_id, fire_utc=fmt_utc(when), ack_state="SNOOZED")
        return
    if a["schedule_kind"] == "ONCE":
        repo.update(alarm_id, ack_state="DISMISSED", enabled=0)
    else:
        repo.update(alarm_id, ack_state="IDLE", fire_utc=None)


def upcoming(alarms: list[dict[str, Any]], tz: ZoneInfo, limit: int = 8) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    items = []
    for a in alarms:
        occ = next_occurrence(a, now)
        if a.get("ack_state") == "SNOOZED" and a.get("fire_utc"):
            occ = _utc(a["fire_utc"])
        if occ:
            items.append({"id": a["id"][:23], "epoch_s": int(occ.timestamp()), "title": (a["title"] or "")[:39],
                          "chime_id": int(a.get("fallback_chime_id") or 4), "enabled": True})
    return sorted(items, key=lambda x: x["epoch_s"])[:limit]


def next_alarm_hhmm(alarms: list[dict[str, Any]], tz: ZoneInfo) -> str:
    up = upcoming(alarms, tz, 1)
    if not up:
        return ""
    return datetime.fromtimestamp(up[0]["epoch_s"], tz).strftime("%H:%M")
