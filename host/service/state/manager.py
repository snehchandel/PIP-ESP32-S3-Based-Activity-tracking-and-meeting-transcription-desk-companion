"""DeviceStateManager: the single canonical state owner (revision + snapshot + change fan-out)."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..storage.db import Database
from ..storage.repo_alarms import AlarmRepo, DeviceRepo
from ..storage.repo_tasks import TaskRepo
from .actions import ActionsMixin
from .reconcile import ReconcileMixin
from .timer import Clock, HostTimer

Listener = Callable[[str, dict[str, Any]], None]
OVERLAYS = {"LISTENING", "TRANSCRIBING", "THINKING", "NEEDS_CONFIRMATION", "STEP_DONE", "BREAK"}
BREAK_MS = 5 * 60 * 1000


def _cut(s: str | None, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


class DeviceStateManager(ActionsMixin, ReconcileMixin):
    def __init__(self, db: Database, tz: str = "America/Toronto", clock: Clock = time.monotonic) -> None:
        self.db = db
        self.tasks = TaskRepo(db)
        self.alarms = AlarmRepo(db)
        self.device = DeviceRepo(db)
        self.tz = ZoneInfo(tz)
        self.clock = clock
        self.lock = threading.RLock()
        self.timer = HostTimer(clock)
        self.brk = HostTimer(clock)
        self.overlay: str | None = None
        self.page = "FOCUS"
        self.done_title = ""
        self.thinking_stage = ""
        self.ringing: dict[str, Any] | None = None
        self.pending: dict[str, Any] | None = None  # plan awaiting time confirmation
        self.error: dict[str, Any] | None = None    # user-visible error screen (dismissed by any button)
        self.weather: dict[str, Any] = {}            # outdoor conditions pushed to the device
        self.ack: dict[str, Any] | None = None       # "Alarm set · Wed 05:00" confirmation toast
        self._ack_seq = int(time.time()) % 1_000_000_000  # unique across host restarts: the device shows each id once
        # chooses the Piper voice for a voice alarm ("female"/"male"); Services wires this to user prefs
        self.voice_for_style: Callable[[str], str | None] = lambda style: None
        self._ov_seen: tuple[str | None, float] = (None, 0.0)
        self.listeners: list[Listener] = []
        self.revision = int(self.device.state().get("revision", 1))
        self._restore_timer()

    # ---- change fan-out ------------------------------------------------------------------
    def subscribe(self, fn: Listener) -> None:
        self.listeners.append(fn)

    def changed(self, kind: str = "state_updated", **extra: Any) -> int:
        self._persist_timer()
        self.revision = self.device.bump_revision()
        payload = {"revision": self.revision, **extra}
        for fn in list(self.listeners):
            try:
                fn(kind, payload)
            except Exception:  # a broken listener must not block state changes
                self.db.log("ERROR", "state", f"listener failed for {kind}")
        return self.revision

    # ---- persistence ------------------------------------------------------------------------
    def _restore_timer(self) -> None:
        st = self.device.state()
        step = self.tasks.get_step(st["active_step_id"]) if st.get("active_step_id") else None
        if step and step["status"] != "COMPLETED":
            total = step["duration_min"] * 60_000
            # A RUNNING timer cannot survive a host restart exactly: resume as PAUSED (no-shame, no loss).
            self.timer.load(int(st.get("remaining_ms") or step["remaining_sec"] * 1000), total, "PAUSED")

    def _persist_timer(self) -> None:
        st = self.active_step()
        if st:
            self.tasks.set_step_remaining(st["id"], self.timer.remaining_ms // 1000)
        self.device.update(timer_state=self.timer.state, remaining_ms=self.timer.remaining_ms)

    # ---- queries -----------------------------------------------------------------------------
    def active_task(self) -> dict[str, Any] | None:
        tid = self.device.state().get("active_task_id")
        return self.tasks.get_task(tid) if tid else None

    def active_step(self) -> dict[str, Any] | None:
        sid = self.device.state().get("active_step_id")
        return self.tasks.get_step(sid) if sid else None

    # ---- errors & stuck-state watchdog -------------------------------------------------------
    STUCK_LIMITS_S = {"LISTENING": 90.0, "TRANSCRIBING": 90.0, "THINKING": 150.0}

    def set_error(self, title: str, text: str) -> None:
        with self.lock:
            self.error = {"title": title[:28], "text": text[:120], "since": self.clock(),
                          "at": datetime.now(UTC).isoformat()}
            if self.overlay in self.STUCK_LIMITS_S:
                self.overlay = None
            self.changed("error_shown", title=title)

    ACK_SHOW_S = 8.0

    def set_ack(self, text: str) -> None:
        """Show a short confirmation on the device (toast) - e.g. that an alarm was created."""
        with self.lock:
            self._ack_seq += 1
            self.ack = {"id": self._ack_seq, "text": text[:38], "since": self.clock()}

    def expire_ack(self) -> bool:
        with self.lock:
            if self.ack and self.clock() - self.ack["since"] >= self.ACK_SHOW_S:
                self.ack = None
                return True
            return False

    def clear_error(self) -> None:
        with self.lock:
            if self.error:
                self.error = None
                self.changed("error_cleared")

    def check_stuck(self) -> bool:
        """Called ~1 Hz: a busy overlay that never finishes becomes a logged error screen."""
        from .. import errors  # local import avoids a cycle
        with self.lock:
            ov = self.overlay
            if ov != self._ov_seen[0]:
                self._ov_seen = (ov, self.clock())
                return False
            limit = self.STUCK_LIMITS_S.get(ov or "")
            age = self.clock() - self._ov_seen[1]
            if limit is None or age < limit:
                return False
            errors.report(self.db, "watchdog", "Stuck state", f"{ov} for {age:.0f}s", None,
                          stage=self.thinking_stage, revision=self.revision)
            self.set_error("PIP got stuck", f"{ov.title()} took too long. Press any button.")
            return True

    def ui_state(self) -> str:
        if self.ringing:
            return "ALARM_RINGING"
        if self.error:
            return "ERROR_RECOVERABLE"
        if self.overlay in OVERLAYS:
            return self.overlay
        if self.timer.state == "RUNNING":
            return "RUNNING"
        if self.timer.state == "PAUSED" and self.timer.started:
            return "PAUSED"
        return "IDLE_READY"

    def tz_offset_min(self) -> int:
        off = datetime.now(self.tz).utcoffset()
        return int(off.total_seconds() // 60) if off else 0

    def snapshot(self) -> dict[str, Any]:
        """UI_UPDATE payload for the device (<= 2048 bytes)."""
        with self.lock:
            task, step = self.active_task(), self.active_step()
            steps = task["steps"] if task else []
            if self.overlay == "STEP_DONE":
                nxt = step  # the step that was just queued up is what "Up next" shows
            else:
                nxt = next((s for s in steps if step and s["position"] > step["position"]
                            and s["status"] == "PENDING"), None)
            idx = next((i for i, s in enumerate(steps) if step and s["id"] == step["id"]), -1)
            from ..alarms.schedule import next_alarm_hhmm  # local import avoids a cycle
            return {
                "rev": self.revision, "ui_state": self.ui_state(), "page": self.page,
                "task_title": _cut((task.get("short_title") or task["title"]) if task else "", 22),
                "step_id": step["id"] if step else "", "step_title": _cut(step["title"] if step else "", 90),
                "step_index": idx + 1 if idx >= 0 else 0, "step_total": len(steps),
                "is_starter": bool(step and step["is_starter"]),
                "timer_state": self.timer.state, "remaining_ms": self.timer.remaining_ms,
                "step_total_ms": self.timer.total_ms,
                "next_step_id": nxt["id"] if nxt else "", "next_step_title": _cut(nxt["title"] if nxt else "", 60),
                "next_step_min": nxt["duration_min"] if nxt else 0,
                "parked_count": len(self.tasks.parked()),
                "next_alarm_hhmm": next_alarm_hhmm(self.alarms.list(), self.tz),
                "clarification_text": _cut((self.pending or {}).get("question", ""), 90),
                "thinking_stage": self.thinking_stage, "done_title": _cut(self.done_title, 90),
                "break_remaining_ms": self.brk.remaining_ms if self.overlay == "BREAK" else 0,
                "tz_offset_min": self.tz_offset_min(), "alarm_ringing": bool(self.ringing),
                "error_title": (self.error or {}).get("title", ""), "error_text": (self.error or {}).get("text", ""),
                "toast": (self.ack or {}).get("text", ""), "toast_id": (self.ack or {}).get("id", 0),
                **{k: v for k, v in self.weather.items() if k in ("out_temp_c10", "out_hum", "out_code")},
            }

    def full_state(self) -> dict[str, Any]:
        with self.lock:
            today = datetime.now(self.tz).date().isoformat()
            return {
                "revision": self.revision, "ui_state": self.ui_state(), "page": self.page,
                "active_task": self.active_task(), "active_step_id": (self.active_step() or {}).get("id"),
                "timer": {"state": self.timer.state, "remaining_ms": self.timer.remaining_ms,
                          "total_ms": self.timer.total_ms, "started": self.timer.started},
                "break_remaining_ms": self.brk.remaining_ms if self.overlay == "BREAK" else 0,
                "tasks": self.tasks.list_tasks(date_from=today),
                "parked": self.tasks.parked(), "reminders": self.tasks.reminders(),
                "alarms": self.alarms.list(), "ringing": self.ringing, "pending_confirmation": self.pending,
                "done_title": self.done_title, "timezone": self.tz.key, "error": self.error, "ack": self.ack,
                "weather": self.weather,
                "server_time_utc": datetime.now(UTC).isoformat(),
            }
