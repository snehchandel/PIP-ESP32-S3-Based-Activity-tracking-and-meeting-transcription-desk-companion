"""Gentle nudges at the right moment: a reminder that is due, a task whose start time has come.

Reminders used to show only on the calendar - nothing told you when they were due. Now, once a check finds one due
(within the last NUDGE_WINDOW_S, so a host restart never replays old ones), PIP shows a toast ("Reminder: ..." /
"Time to start: ..."), chimes and says it (Services._nudge).

Focus is protected: a task's start time that comes while you are mid-step on *another* task (its timer running)
waits silently and is mentioned once at the next natural break (step done, pause, break): "Next: ... (09:29)".
No nudge for the task you have already begun. Reminders (hard times, e.g. a meeting) still ping."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..state.manager import DeviceStateManager

NUDGE_WINDOW_S = 120


def _spoken_time(hhmm: str) -> str:
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    return f"{(h - 1) % 12 + 1}:{m:02d}" if m else f"{(h - 1) % 12 + 1} o'clock"


class NudgeScheduler:
    def __init__(self, manager: DeviceStateManager) -> None:
        self.m = manager
        self.done: set[str] = set()  # "<id>@<due>" already handled (a moved item nudges again at its new time)
        self.waiting: dict[str, dict[str, str]] = {}  # start nudges held back while focusing: key -> task info

    def _focusing(self) -> bool:
        return self.m.timer.state == "RUNNING" and self.m.overlay not in ("STEP_DONE", "BREAK")

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
        active_id = self.m.device.state().get("active_task_id")
        for t in self.m.tasks.list_tasks(today, today, include_done=False):
            hhmm = t.get("start_hhmm")
            if not hhmm or t["status"] in ("COMPLETED", "ARCHIVED"):
                continue
            key = f"{t['id']}@{today}T{hhmm}"
            at = local.replace(hour=int(hhmm[:2]), minute=int(hhmm[3:5]), second=0, microsecond=0)
            if key in self.done or not 0 <= (local - at).total_seconds() <= NUDGE_WINDOW_S:
                continue
            begun = self.m.timer.started or any(s["status"] == "COMPLETED" for s in t.get("steps") or [])
            if t["id"] == active_id and begun:  # already working on it: nothing to say
                self.done.add(key)
                continue
            name = t.get("short_title") or t["title"]
            if self._focusing():  # mid-step on another task: hold it for the next natural break
                self.done.add(key)
                self.waiting[key] = {"id": t["id"], "name": name, "title": t["title"], "hhmm": hhmm}
                continue
            due.append((key, f"Time to start: {name}", f"Time to start: {t['title']}. Press KEY when you're ready."))
        if self.waiting and not self._focusing():
            for key, w in list(self.waiting.items()):
                self.waiting.pop(key)
                task = self.m.tasks.get_task(w["id"])
                if task is None or task["status"] in ("COMPLETED", "ARCHIVED") or w["id"] == active_id \
                        or task["target_date"] != today:
                    continue  # finished, parked, moved or picked up meanwhile
                due.append((key + "#next", f"Next: {w['name']} ({w['hhmm']})",
                             f"When you're ready: {w['title']} was planned for {_spoken_time(w['hhmm'])}."))
                break  # one at a time; the rest at the following break
        fired = []
        for key, toast, spoken in due:
            if key in self.done and not key.endswith("#next"):
                continue
            self.done.add(key)
            with self.m.lock:
                self.m.set_ack(toast)
                self.m.changed("nudge", text=toast)
            fired.append(spoken)
        return fired
