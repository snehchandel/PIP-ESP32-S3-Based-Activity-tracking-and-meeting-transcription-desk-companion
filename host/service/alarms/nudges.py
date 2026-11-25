"""Gentle nudges at the right moment: a reminder that is due, a task whose start time has come.

Reminders used to show only on the calendar - nothing told you when they were due. Now, once a minute-accurate
check finds one due (within the last NUDGE_WINDOW_S, so a host restart never replays old ones), PIP shows a toast
("Reminder: ..." / "Time to start: ..."), chimes and says it (Services._nudge)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..state.manager import DeviceStateManager

NUDGE_WINDOW_S = 120


class NudgeScheduler:
    def __init__(self, manager: DeviceStateManager) -> None:
        self.m = manager
        self.done: set[str] = set()  # "<id>@<due>" already nudged (a moved item nudges again at its new time)

    def check(self, now: datetime | None = None) -> list[str]:
        """Returns the spoken texts of the nudges fired now (the toast is set on the manager)."""
        now = now or datetime.now(UTC)
        due: list[tuple[str, str, str]] = []  # (key, toast, spoken)
        for r in self.m.tasks.reminders():
            if r.get("done"):
                continue
            at = datetime.strptime(r["due_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            if 0 <= (now - at).total_seconds() <= NUDGE_WINDOW_S:
                due.append((f"{r['id']}@{r['due_utc']}", f"Reminder: {r['title']}", f"Reminder: {r['title']}."))
        local = now.astimezone(self.m.tz)
        today = local.date().isoformat()
        for t in self.m.tasks.list_tasks(today, today, include_done=False):
            hhmm = t.get("start_hhmm")
            if not hhmm or t["status"] in ("COMPLETED", "ARCHIVED"):
                continue
            at = local.replace(hour=int(hhmm[:2]), minute=int(hhmm[3:5]), second=0, microsecond=0)
            if 0 <= (local - at).total_seconds() <= NUDGE_WINDOW_S:
                name = t.get("short_title") or t["title"]
                due.append((f"{t['id']}@{today}T{hhmm}", f"Time to start: {name}",
                            f"Time to start: {t['title']}. Press KEY when you're ready."))
        fired = []
        for key, toast, spoken in due:
            if key in self.done:
                continue
            self.done.add(key)
            with self.m.lock:
                self.m.set_ack(toast)
                self.m.changed("nudge", text=toast)
            fired.append(spoken)
        return fired
