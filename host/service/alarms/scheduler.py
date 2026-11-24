"""AlarmScheduler: fires due alarms exactly once per occurrence (survives host restarts via last_fired_utc)."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..state.manager import DeviceStateManager
from .schedule import due_alarms, fmt_utc

log = logging.getLogger("pip.alarms")


class AlarmScheduler:
    def __init__(self, manager: DeviceStateManager) -> None:
        self.m = manager
        self.missed: list[str] = []

    def check(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(UTC)
        fired: list[str] = []
        for a in due_alarms(self.m.alarms.list(), now):
            self.m.alarms.update(a["id"], last_fired_utc=fmt_utc(a["_occurrence"]))
            if a["_late"]:
                # host was off when it was due: never ring a stale alarm, keep a calm note instead
                self.missed.append(a["id"])
                if a["schedule_kind"] == "ONCE":
                    self.m.alarms.update(a["id"], ack_state="MISSED", enabled=0)
                self.m.db.log("INFO", "alarm", f"missed alarm {a['id']} (host offline)")
                continue
            if self.m.ringing:
                continue  # one alarm at a time; the other fires on the next check
            self.m.ring(a)
            fired.append(a["id"])
        return fired

    def test(self, alarm_id: str) -> bool:
        a = self.m.alarms.get(alarm_id)
        if a is None:
            return False
        self.m.ring(a, test=True)
        return True
