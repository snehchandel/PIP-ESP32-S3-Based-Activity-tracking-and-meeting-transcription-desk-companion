"""A rebooted or out-of-date PIP gets the full state again; the board's "Coming up" list.

A USB reboot (OTA update, watchdog) reconnects inside the link's grace period, so no link-down/link-up is seen.
Before this fix PIP then sat there blank: UTC clock, no weather, no next alarm, no agenda."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from service.calendar.agenda import calendar_sync, upcoming_items
from service.device import link as link_mod
from service.device.link import DeviceLink
from service.protocol import Frame, FrameType, Heartbeat


def _link(manager):  # type: ignore[no-untyped-def]
    link = DeviceLink(manager, None, None, lambda k, p: None)
    sent: list[int] = []
    link.send = lambda ftype, payload=b"", ack=False: sent.append(ftype) or True  # type: ignore[method-assign]
    hooks: list[str] = []
    link.on_link_up = hooks.append
    link.linked = True
    return link, sent, hooks


def _hb(uptime: int, rev: int) -> Frame:
    return Frame(FrameType.HEARTBEAT, 0, 1, Heartbeat(1, 1, 0, uptime, 0, rev).pack())


def test_restart_triggers_full_resync(manager) -> None:  # type: ignore[no-untyped-def]
    link, sent, hooks = _link(manager)
    rev = manager.revision
    link._dispatch(_hb(500, rev))
    link._dispatch(_hb(501, rev))
    assert sent == [] and hooks == []
    link._dispatch(_hb(2, 0))  # uptime went backwards: PIP rebooted
    assert FrameType.UI_UPDATE in sent and FrameType.CALENDAR_SYNC in sent
    assert hooks == [link.transport_kind]  # device config (wake word, token over USB) goes out again too


def test_stale_device_is_resynced_once(manager, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    link, sent, _ = _link(manager)
    monkeypatch.setattr(link_mod, "STALE_RESYNC_S", 0.0)
    manager.revision += 5
    link._dispatch(_hb(10, manager.revision - 5))  # first sight: starts the stale clock
    link._dispatch(_hb(11, manager.revision - 5))
    assert sent.count(FrameType.UI_UPDATE) >= 1
    n = len(sent)
    link._dispatch(_hb(12, manager.revision))  # caught up: nothing more
    assert len(sent) == n


def test_upcoming_lists_next_days_open_items_soonest_first() -> None:
    tz = ZoneInfo("America/Toronto")
    today = datetime.now(tz).date()
    d1, d3 = today + timedelta(days=1), today + timedelta(days=3)
    tasks = [
        {"id": "t1", "title": "Dentist", "target_date": d3.isoformat(), "status": "SCHEDULED", "start_hhmm": "10:30",
         "steps": []},
        {"id": "t2", "title": "Draft Q3 summary", "target_date": d1.isoformat(), "status": "SCHEDULED",
         "start_hhmm": "", "steps": []},
        {"id": "t3", "title": "Done already", "target_date": d1.isoformat(), "status": "COMPLETED", "steps": []},
        {"id": "t4", "title": "Today thing", "target_date": today.isoformat(), "status": "SCHEDULED", "steps": []},
    ]
    fire = datetime.combine(d1, datetime.min.time(), tz).replace(hour=5).astimezone(UTC)
    alarms = [{"id": "a1", "title": "Gym wake-up", "enabled": 1, "schedule_kind": "ONCE",
               "fire_utc": fire.strftime("%Y-%m-%dT%H:%M:%SZ"), "local_hhmm": "05:00"}]
    up = upcoming_items(tasks, [], alarms, today, tz)
    assert [(u["day"], u["hhmm"], u["title"]) for u in up] == [
        (d1.strftime("%a"), "05:00", "Gym wake-up"),
        (d1.strftime("%a"), "", "Draft Q3 summary"),
        (d3.strftime("%a"), "10:30", "Dentist"),
    ]
    sync = calendar_sync(tasks, [], alarms, 0, tz, 1)
    assert sync["upcoming"] == up and [i["title"] for i in sync["today"]] == ["Today thing"]
