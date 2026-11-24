"""DST normalisation, alarm occurrence math, snooze/dismiss, exactly-once firing across restarts."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from service.alarms.schedule import apply_ack, due_alarms, fmt_utc, next_occurrence, upcoming
from service.alarms.scheduler import AlarmScheduler
from service.calendar.timeparse import parse_when, resolve_local

from ..conftest import TZ


def test_spring_forward_gap_shifts_to_first_valid_instant() -> None:
    local, note = resolve_local(date(2026, 3, 8), time(2, 30), TZ)
    assert (local.hour, local.minute) == (3, 0) and "gap" in note


def test_fall_back_overlap_uses_first_occurrence() -> None:
    local, note = resolve_local(date(2026, 11, 1), time(1, 30), TZ)
    assert local.utcoffset() == timedelta(hours=-4) and "ambiguous" in note


def test_normal_time_has_no_note() -> None:
    local, note = resolve_local(date(2026, 6, 1), time(9, 0), TZ)
    assert note == "" and local.utcoffset() == timedelta(hours=-4)


def test_parse_exact_vs_vague(now) -> None:  # type: ignore[no-untyped-def]
    assert parse_when("at 3pm", now, TZ).needs_confirmation is False  # type: ignore[union-attr]
    assert parse_when("friday afternoon", now, TZ).needs_confirmation is True  # type: ignore[union-attr]
    later = parse_when("sometime later", now, TZ)
    assert later is not None and later.local is None and later.needs_confirmation
    assert parse_when("buy milk", now, TZ) is None
    past = parse_when("at 9am", now, TZ)  # 9am already passed at 10:00 -> tomorrow
    assert past is not None and past.local is not None and past.local.day == 24


def _alarm(**kw):  # type: ignore[no-untyped-def]
    base = {"id": "alarm_x", "title": "Gym", "schedule_kind": "RECURRING", "rrule_days": "MO,WE,FR",
            "local_hhmm": "07:00", "timezone": "America/Toronto", "enabled": 1, "ack_state": "IDLE",
            "fire_utc": None, "last_fired_utc": None, "snooze_min": 5, "fallback_chime_id": 4}
    base.update(kw)
    return base


def test_recurring_next_occurrence_across_dst() -> None:
    after = datetime(2026, 3, 6, 13, 0, tzinfo=timezone.utc)  # Friday afternoon before spring-forward
    occ = next_occurrence(_alarm(), after)
    assert occ is not None
    local = occ.astimezone(TZ)
    assert local.weekday() == 0 and (local.hour, local.minute) == (7, 0)  # Monday 07:00 local, now EDT
    assert occ.hour == 11  # 07:00 EDT == 11:00 UTC


def test_once_alarm_fires_once_then_never(manager) -> None:  # type: ignore[no-untyped-def]
    t0 = datetime.now(timezone.utc)
    aid = manager.alarms.create(title="Call", schedule_kind="ONCE", fire_utc=fmt_utc(t0 - timedelta(seconds=5)),
                                local_hhmm="15:00", timezone="America/Toronto")
    sched = AlarmScheduler(manager)
    assert sched.check(t0) == [aid]
    assert manager.ui_state() == "ALARM_RINGING"
    manager.ack_alarm(snooze=False)
    assert sched.check(t0 + timedelta(seconds=2)) == []
    assert manager.alarms.get(aid)["enabled"] == 0


def test_restart_does_not_refire(manager) -> None:  # type: ignore[no-untyped-def]
    t0 = datetime.now(timezone.utc)
    manager.alarms.create(title="Call", schedule_kind="ONCE", fire_utc=fmt_utc(t0 - timedelta(seconds=5)),
                          local_hhmm="15:00", timezone="America/Toronto")
    AlarmScheduler(manager).check(t0)
    manager.ringing = None  # simulated host restart: in-memory ring state is gone
    manager.alarms.update(manager.alarms.list()[0]["id"], ack_state="IDLE")
    assert AlarmScheduler(manager).check(t0 + timedelta(seconds=1)) == []


def test_missed_alarm_is_not_rung_late(manager) -> None:  # type: ignore[no-untyped-def]
    t0 = datetime.now(timezone.utc)
    aid = manager.alarms.create(title="Old", schedule_kind="ONCE", fire_utc=fmt_utc(t0 - timedelta(minutes=5)),
                                local_hhmm="09:00", timezone="America/Toronto", last_fired_utc=None)
    # due_alarms only looks back MISSED_GRACE; anything older than that while offline is marked missed
    due = due_alarms(manager.alarms.list(), t0 + timedelta(minutes=30))
    assert due == [] or due[0]["_late"]
    sched = AlarmScheduler(manager)
    sched.check(t0 + timedelta(minutes=30))
    assert manager.ringing is None
    assert manager.alarms.get(aid) is not None


def test_snooze_moves_fire_time(manager) -> None:  # type: ignore[no-untyped-def]
    t0 = datetime.now(timezone.utc)
    aid = manager.alarms.create(title="Meds", schedule_kind="ONCE", fire_utc=fmt_utc(t0 - timedelta(seconds=1)),
                                local_hhmm="21:00", timezone="America/Toronto", snooze_min=5)
    AlarmScheduler(manager).check(t0)
    manager.ack_alarm(snooze=True)
    a = manager.alarms.get(aid)
    fire = datetime.strptime(a["fire_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert a["ack_state"] == "SNOOZED" and timedelta(minutes=4) < fire - t0 < timedelta(minutes=6)
    assert AlarmScheduler(manager).check(fire + timedelta(seconds=1)) == [aid]


def test_device_snooze_via_key_click(manager) -> None:  # type: ignore[no-untyped-def]
    aid = manager.alarms.create(title="Gym", schedule_kind="ONCE", fire_utc=fmt_utc(datetime.now(timezone.utc)),
                                local_hhmm="07:00", timezone="America/Toronto")
    manager.ring(manager.alarms.get(aid))
    assert manager.apply_button(0, 1) == "alarm_snooze"
    assert manager.ringing is None and manager.alarms.get(aid)["ack_state"] == "SNOOZED"


def test_recurring_dismiss_keeps_schedule(manager) -> None:  # type: ignore[no-untyped-def]
    aid = manager.alarms.create(**{k: v for k, v in _alarm().items() if k != "id"})
    apply_ack(manager.alarms, aid, snooze=False)
    a = manager.alarms.get(aid)
    assert a["enabled"] == 1 and a["ack_state"] == "IDLE"
    assert upcoming([a], TZ)  # still scheduled for its next weekday
