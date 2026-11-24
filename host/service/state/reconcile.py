"""Plan commits, time-confirmation flow, alarm ring/ack and idempotent offline-event reconciliation (D11)."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..planner.schema import IntentType, PlannerOutputV1

TEST_RING_S = 30  # "Test on device" rings auto-dismiss after this many seconds

if TYPE_CHECKING:
    from .manager import DeviceStateManager


def pretty_when(due_local: str) -> str:
    """'2026-11-27T14:00' -> 'Friday at 2:00 PM' (portable: no %-I)."""
    dt = datetime.fromisoformat(due_local)
    return f"{dt.strftime('%A')} at {(dt.hour % 12) or 12}:{dt.minute:02d} {'PM' if dt.hour >= 12 else 'AM'}"


class ReconcileMixin:
    # ---- plans -----------------------------------------------------------------------------
    def commit_plan(self: DeviceStateManager, plan: PlannerOutputV1, source_text: str = "",
                    activate: bool = True) -> dict[str, Any]:
        """Transactionally apply a validated plan. Ambiguous times are held for confirmation, never armed."""
        with self.lock:
            out: dict[str, Any] = {"task_id": None, "parked_ids": [], "scheduled_ids": [], "held": []}
            if plan.control is not None:
                actions = {"START": self.timer_start, "PAUSE": self.timer_pause, "RESUME": self.timer_start,
                           "BREAK": self.start_break, "RESET": self.timer_reset,
                           "COMPLETE_STEP": self.complete_step, "SPLIT_STEP": self.rescue_split}
                actions[plan.control.action]()
                out["control"] = plan.control.action
                return out
            today = datetime.now(self.tz).date().isoformat()
            if plan.active_task:
                tid = self.tasks.create_task(plan.active_task.title, [s.model_dump() for s in plan.active_task.steps],
                                             today, self.tz.key, if_then_cue=plan.active_task.if_then_cue)
                out["task_id"] = tid
            for p in plan.parked:
                out["parked_ids"].append(self.tasks.park(p.title, p.source_text))
            for item in plan.scheduled:
                if item.needs_confirmation or not item.due_local:
                    out["held"].append(item.model_dump())
                    continue
                out["scheduled_ids"].append(self._schedule_item(item.model_dump()))
            if out["held"]:
                first = out["held"][0]
                when = first.get("due_local")
                question = f"{first['title']}: {pretty_when(when) if when else (first.get('when_text') or 'when')}?"
                self.pending = {"items": out["held"], "question": question}
                self.overlay = "NEEDS_CONFIRMATION"
            if out["task_id"] and activate and (self.active_step() is None):
                self.activate_task(out["task_id"])
            elif plan.intent == IntentType.NEEDS_CLARIFICATION:
                self.pending = {"items": [], "question": plan.clarification_question or "Can you say more?"}
                self.overlay = "NEEDS_CONFIRMATION"
                self.changed()
            else:
                self.changed()
            return out

    def _schedule_item(self: DeviceStateManager, item: dict[str, Any]) -> str:
        local = datetime.fromisoformat(item["due_local"]).replace(tzinfo=self.tz)
        utc = local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if item["kind"] == "ALARM":
            return self.alarms.create(title=item["title"], schedule_kind="ONCE", fire_utc=utc,
                                      local_hhmm=local.strftime("%H:%M"), timezone=self.tz.key, audio_mode="CHIME")
        if item["kind"] == "TASK":
            from ..planner.step_templates import steps_for
            return self.tasks.create_task(item["title"], steps_for(item["title"]), local.date().isoformat(),
                                          self.tz.key, start_hhmm=local.strftime("%H:%M"))
        return self.tasks.add_reminder(item["title"], utc, self.tz.key)

    def confirm_pending(self: DeviceStateManager, items: list[dict[str, Any]] | None = None) -> list[str]:
        with self.lock:
            ids: list[str] = []
            for it in items if items is not None else (self.pending or {}).get("items", []):
                if it.get("due_local"):
                    ids.append(self._schedule_item(it))
            self.pending = None
            if self.overlay == "NEEDS_CONFIRMATION":
                self.overlay = None
            self.changed()
            return ids

    def dismiss_pending(self: DeviceStateManager) -> None:
        with self.lock:
            for it in (self.pending or {}).get("items", []):
                self.tasks.park(it["title"], it.get("when_text") or "")  # keep the thought, drop the time
            self.pending = None
            if self.overlay == "NEEDS_CONFIRMATION":
                self.overlay = None
            self.changed()

    # ---- alarms ------------------------------------------------------------------------------
    def ring(self: DeviceStateManager, alarm: dict[str, Any], test: bool = False) -> None:
        """test=True: a preview from the app. It auto-clears after TEST_RING_S and never changes the
        alarm's stored state (a tested one-time alarm stays armed)."""
        with self.lock:
            self.ringing = {"id": alarm["id"], "title": alarm["title"], "hhmm": alarm["local_hhmm"],
                            "audio_mode": alarm.get("audio_mode") or "CHIME", "snooze_min": alarm.get("snooze_min", 5),
                            "tts_script": alarm.get("tts_script") or "", "test": test, "since": self.clock(),
                            "auto_dismiss_s": TEST_RING_S if test else None,
                            "expires_at_ms": int(time.time() * 1000) + TEST_RING_S * 1000 if test else None}
            if not test:
                self.alarms.update(alarm["id"], ack_state="RINGING")
            self.changed("alarm_triggered", alarm_id=alarm["id"])

    def ack_alarm(self: DeviceStateManager, snooze: bool) -> None:
        from ..alarms.schedule import apply_ack  # local import avoids a cycle
        with self.lock:
            if not self.ringing:
                return
            if not self.ringing.get("test"):
                apply_ack(self.alarms, self.ringing["id"], snooze)
            self.ringing = None
            self.changed("alarm_cleared")

    def expire_test_ring(self: DeviceStateManager) -> bool:
        """Called ~1 Hz: a test ring that nobody dismissed goes away by itself."""
        with self.lock:
            r = self.ringing
            if r and r.get("test") and self.clock() - r["since"] >= TEST_RING_S:
                self.ringing = None
                self.changed("alarm_cleared", reason="test_timeout")
                return True
            return False

    # ---- offline reconciliation -------------------------------------------------------------------
    def apply_offline_events(self: DeviceStateManager, events: list[dict[str, Any]]) -> int:
        """Ingest device offline events idempotently by (boot_id, seq); returns how many were new."""
        applied = 0
        with self.lock:
            for ev in sorted(events, key=lambda e: int(e.get("seq", 0))):
                boot, seq = int(ev.get("boot_id", 0)), int(ev.get("seq", 0))
                kind, ref = str(ev.get("kind", "")), str(ev.get("ref_id", ""))
                rem = int(ev.get("remaining_ms", 0))
                if not self.device.record_device_event(boot, seq, kind, ref, rem, int(ev.get("ts_epoch", 0))):
                    continue
                applied += 1
                step = self.tasks.get_step(ref) if ref else None
                if kind == "STEP_COMPLETE" and step and step["status"] != "COMPLETED":
                    self.complete_step(ref)
                    self.overlay = None
                elif kind == "STEP_SPLIT" and step and step["status"] != "COMPLETED":
                    self.rescue_split(ref)
                elif kind == "TIMER_DELTA" and step and step["status"] != "COMPLETED":
                    if (self.active_step() or {}).get("id") == ref:
                        self.timer.load(rem, self.timer.total_ms, "PAUSED")
                    else:
                        self.tasks.set_step_remaining(ref, rem // 1000)
                elif kind == "ALARM_ACK" and self.alarms.get(ref):
                    from ..alarms.schedule import apply_ack
                    apply_ack(self.alarms, ref, snooze=rem == 1)
            if applied:
                self.device.update(last_boot_id=int(events[-1].get("boot_id", 0)) if events else None)
                self.changed("offline_reconciled", applied=applied)
        return applied
