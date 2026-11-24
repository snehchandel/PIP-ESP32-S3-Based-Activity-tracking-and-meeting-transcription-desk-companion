"""Timer, step and button actions (host mirror of the firmware gesture matrix, spec 5.3)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .manager import DeviceStateManager

KEY, BOOT = 0, 1
SHORT, DOUBLE, HOLD_START, HOLD_END, RESCUE = 1, 2, 3, 4, 5


def split_calc(remaining_sec: int) -> tuple[int, int]:
    """Same rule as firmware lt_split_calc: never loses work, each half >= 120 s."""
    cur = max(120, remaining_sec // 2)
    nxt = max(120, remaining_sec - cur)
    return cur, nxt


class ActionsMixin:
    # ---- activation ----------------------------------------------------------------------
    def activate_task(self: DeviceStateManager, tid: str) -> None:
        with self.lock:
            task = self.tasks.get_task(tid)
            if task is None:
                raise KeyError(tid)
            self.tasks.set_active(tid)
            step = next((s for s in task["steps"] if s["status"] != "COMPLETED"), None)
            self._load_step(step, tid)
            self.overlay = None
            self.changed()

    def _load_step(self: DeviceStateManager, step: dict[str, Any] | None, tid: str | None) -> None:
        if step is None:
            self.timer.load(0, 0, "STOPPED")
            self.device.update(active_task_id=tid, active_step_id=None)
            return
        self.tasks.set_step_status(step["id"], "ACTIVE")
        self.timer.load(step["remaining_sec"] * 1000, step["duration_min"] * 60_000, "PAUSED")
        self.device.update(active_task_id=tid, active_step_id=step["id"])

    # ---- timer ------------------------------------------------------------------------------
    def timer_start(self: DeviceStateManager) -> bool:
        with self.lock:
            if self.active_step() is None:
                return False
            if self.overlay in ("STEP_DONE", "BREAK"):
                self.overlay = None
                self.brk.stop()
            ok = self.timer.start()
            self.changed()
            return ok

    def timer_pause(self: DeviceStateManager) -> bool:
        with self.lock:
            ok = self.timer.pause()
            self.changed()
            return ok

    def timer_toggle(self: DeviceStateManager) -> None:
        if self.timer.state == "RUNNING":
            self.timer_pause()
        else:
            self.timer_start()

    def timer_reset(self: DeviceStateManager) -> None:
        with self.lock:
            st = self.active_step()
            if st:
                self.timer.load(st["duration_min"] * 60_000, st["duration_min"] * 60_000, "PAUSED")
            self.changed()

    def start_break(self: DeviceStateManager, minutes: int = 5) -> None:
        with self.lock:
            self.timer.pause()
            self.brk.load(minutes * 60_000, minutes * 60_000, "RUNNING")
            self.brk.start()
            self.overlay = "BREAK"
            self.changed()

    def end_break(self: DeviceStateManager) -> None:
        with self.lock:
            self.brk.stop()
            self.overlay = None
            self.changed()

    # ---- steps --------------------------------------------------------------------------------
    def complete_step(self: DeviceStateManager, step_id: str | None = None) -> dict[str, Any] | None:
        with self.lock:
            step = self.tasks.get_step(step_id) if step_id else self.active_step()
            if step is None or step["status"] == "COMPLETED":
                return None
            self.tasks.set_step_status(step["id"], "COMPLETED", 0)
            self.done_title = step["title"]
            task = self.tasks.get_task(step["task_id"])
            nxt = next((s for s in (task or {}).get("steps", []) if s["status"] == "PENDING"), None)
            active = self.device.state().get("active_task_id") == step["task_id"]
            if active:
                if nxt is None:
                    self.tasks.update_task(step["task_id"], status="COMPLETED")
                    self._load_step(None, None)
                else:
                    self.tasks.set_step_status(nxt["id"], "PENDING")
                    self.timer.load(nxt["remaining_sec"] * 1000, nxt["duration_min"] * 60_000, "PAUSED")
                    self.device.update(active_step_id=nxt["id"])
                self.overlay = "STEP_DONE"
            self.changed(completed_step=step["id"])
            return step

    def start_next_step(self: DeviceStateManager) -> None:
        with self.lock:
            st = self.active_step()
            self.overlay = None
            if st:
                self.tasks.set_step_status(st["id"], "ACTIVE")
                self.timer.start()
            self.changed()

    def rescue_split(self: DeviceStateManager, step_id: str | None = None,
                     remaining_sec: int | None = None) -> tuple[int, int] | None:
        with self.lock:
            step = self.tasks.get_step(step_id) if step_id else self.active_step()
            if step is None or step["status"] == "COMPLETED":
                return None
            is_active = (self.active_step() or {}).get("id") == step["id"]
            rem = remaining_sec if remaining_sec is not None else (
                (self.timer.remaining_ms + 999) // 1000 if is_active else step["remaining_sec"])
            cur, nxt = split_calc(rem)
            self.tasks.split_step(step["id"], cur, nxt)
            if is_active:
                state = "RUNNING" if self.timer.state == "RUNNING" else "PAUSED"
                self.timer.load(cur * 1000, cur * 1000, "PAUSED")
                if state == "RUNNING":
                    self.timer.start()
            self.changed(split_step=step["id"])
            return cur, nxt

    # ---- device buttons ---------------------------------------------------------------------------
    def apply_button(self: DeviceStateManager, btn: int, gesture: int, flags: int = 0) -> str:
        """Apply a device BTN_EVENT with exactly the firmware's semantics. Returns an action label."""
        with self.lock:
            if self.ringing:
                if gesture == HOLD_END:
                    return "ignored"
                snooze = btn == KEY and gesture == SHORT
                self.ack_alarm(snooze)
                return "alarm_snooze" if snooze else "alarm_dismiss"
            if btn == KEY:
                if gesture == SHORT:
                    if self.overlay == "NEEDS_CONFIRMATION":
                        self.dismiss_pending()
                        return "confirm_dismiss"
                    if self.overlay == "STEP_DONE":
                        self.start_next_step()
                        return "next_step"
                    self.timer_toggle()
                    return "timer_toggle"
                if gesture == DOUBLE:
                    self.page = "AGENDA" if self.page == "FOCUS" else "FOCUS"
                    self.changed()
                    return "page_toggle"
                if gesture == HOLD_START:
                    self.overlay = "LISTENING"
                    self.changed()
                    return "listening"
                if gesture == HOLD_END:
                    if self.overlay == "LISTENING":
                        self.overlay = "TRANSCRIBING"
                        self.changed()
                    return "transcribing"
                return "ignored"
            if gesture == RESCUE:
                return "split" if self.rescue_split() else "ignored"
            if gesture != SHORT:
                return "ignored"
            if self.page == "AGENDA":
                self.page = "FOCUS"
                self.changed()
                return "page_focus"
            if self.overlay == "NEEDS_CONFIRMATION":
                self.confirm_pending()
                return "confirm"
            if self.overlay == "STEP_DONE":
                self.start_break()
                return "break"
            if self.overlay == "BREAK":
                self.end_break()
                return "break_end"
            if self.active_step():
                self.complete_step()
                return "complete"
            return "ignored"

    # ---- periodic --------------------------------------------------------------------------------
    def tick(self: DeviceStateManager) -> bool:
        """Called ~1 Hz. Returns True if canonical state changed."""
        with self.lock:
            if self.expire_test_ring():
                return True
            if self.timer.expired():
                self.timer.stop()
                self.complete_step()
                return True
            if self.overlay == "BREAK" and self.brk.expired():
                self.end_break()
                return True
            return False
