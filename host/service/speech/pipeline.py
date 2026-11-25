"""Voice pipeline: device PCM stream -> STT -> Kimi planner (per activity) -> commit/confirmation.

Every stage is guarded: any failure is logged to data/logs/errors.log + event_log and the device shows an
error screen instead of hanging. Kimi is the only planner; if it is unavailable the device shows
"AI has left the device" and the user's words are kept as a parked note so nothing is lost."""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from .. import errors
from ..planner import BudgetExceeded, PlannerError, PlannerOutputV1, TaskPlanner
from ..state.manager import DeviceStateManager
from .stt import SpeechToText

log = logging.getLogger("pip.voice")
MAX_SECONDS = 600  # a voice message may run 10 minutes (meetings have no limit: see meetings/service.py)
MAX_BYTES = MAX_SECONDS * 16000 * 2  # of 16 kHz mono PCM16
ACTIVITIES = ["BRAIN_DUMP", "CALENDAR", "FOCUS", "ALARMS", "MEETING"]  # device AUDIO_START activity byte
MEETING = 4
AI_GONE = ("AI has left the device", "Kimi couldn't be reached. Your words are saved as a parked note.")
AI_BUDGET = ("AI budget reached", "This month's Kimi cap is spent. Words parked; raise the cap in Settings.")


class AiUnavailable(RuntimeError):
    pass


class VoicePipeline:
    def __init__(self, manager: DeviceStateManager, stt: SpeechToText, planner: Callable[[], TaskPlanner],
                 notify: Callable[[str, dict[str, Any]], None]) -> None:
        self.m = manager
        self.stt = stt
        self.planner = planner
        self.notify = notify
        self.streams: dict[int, bytearray] = {}
        self.activity: dict[int, str] = {}
        self.last: dict[str, Any] = {"status": "IDLE"}
        self.meetings: Any = None  # MeetingService: records activity 4 (MEETING) streams to disk

    def start(self, stream_id: int, activity: int = 0) -> None:
        if activity == MEETING and self.meetings is not None:
            self.meetings.start(stream_id)
            return
        self.streams = {stream_id: bytearray()}
        self.activity = {stream_id: ACTIVITIES[activity] if 0 <= activity < len(ACTIVITIES) else "BRAIN_DUMP"}
        self._set_overlay("LISTENING", "")
        self._status("LISTENING", stream_id=stream_id, activity=self.activity[stream_id])

    def data(self, stream_id: int, pcm: bytes, seq: int | None = None) -> None:
        if self.meetings is not None and self.meetings.owns(stream_id):
            self.meetings.data(stream_id, pcm, seq)
            return
        buf = self.streams.get(stream_id)
        if buf is not None and len(buf) + len(pcm) <= MAX_BYTES:
            buf += pcm

    def end(self, stream_id: int, total_samples: int) -> None:
        if self.meetings is not None and self.meetings.owns(stream_id):
            self.meetings.end(stream_id)
            return
        pcm = bytes(self.streams.pop(stream_id, b""))
        activity = self.activity.pop(stream_id, "BRAIN_DUMP")
        threading.Thread(target=self._process, args=(stream_id, pcm, activity), daemon=True, name="pip-voice").start()

    def _status(self, status: str, **extra: Any) -> None:
        self.last = {"status": status, **extra}
        self.notify("voice_session_updated", self.last)

    def _set_overlay(self, overlay: str | None, stage: str = "") -> None:
        with self.m.lock:
            self.m.overlay = overlay
            self.m.thinking_stage = stage
            self.m.changed()

    def _process(self, stream_id: int, pcm: bytes, activity: str) -> None:
        key = f"stream-{stream_id}-{len(pcm)}"
        try:
            self._set_overlay("TRANSCRIBING", "Transcribing...")
            self._status("TRANSCRIBING", seconds=round(len(pcm) / 32000, 1))
            try:
                text = self.stt.transcribe(pcm) if pcm else ""
            except Exception as e:
                errors.report(self.m.db, "voice", "Speech-to-text failed", str(e), e, seconds=len(pcm) / 32000)
                self._set_overlay(None)
                self.m.set_error("Couldn't hear that", "Speech-to-text failed. Please try again.")
                self._status("STT_ERROR", error=str(e)[:160])
                return
            if not text:
                self._set_overlay(None)
                self._status("EMPTY", seconds=round(len(pcm) / 32000, 1))
                return
            self.process_text(text, key, source="voice", auto_commit=True, activity=activity)
        except AiUnavailable:
            pass  # already reported and shown
        except Exception as e:  # anything unexpected: never leave the device on "Planning..."
            errors.report(self.m.db, "voice", "Voice pipeline crashed", str(e), e, activity=activity)
            self._set_overlay(None)
            self.m.set_error("Something went wrong", "PIP lost track of that request. Please try again.")
            self._status("ERROR", error=str(e)[:160])

    def _complete_wake_scripts(self, planner: Any, plan: PlannerOutputV1) -> None:
        """A voice alarm whose script came back missing or short gets a dedicated ~30 s script from Kimi;
        if that fails too, the built-in script is used when it rings (never block the alarm itself)."""
        for item in plan.scheduled:
            if item.needs_script and hasattr(planner, "wake_script"):
                try:
                    item.script = planner.wake_script(item.title)
                except PlannerError as e:
                    errors.report(self.m.db, "planner", "Wake-up script failed", str(e), None, title=item.title)

    def process_text(self, text: str, key: str, source: str = "text", auto_commit: bool = False,
                     activity: str = "BRAIN_DUMP") -> dict[str, Any]:
        if source == "voice":
            self._set_overlay("THINKING", "Breaking into steps..." if activity == "BRAIN_DUMP" else "Thinking...")
        try:
            planner = self.planner()
            plan: PlannerOutputV1 = planner.plan(text, activity=activity)  # type: ignore[call-arg]
        except PlannerError as e:
            errors.report(self.m.db, "planner", "Kimi unavailable", str(e), None, activity=activity, source=source)
            self.m.device.add_voice_session(key, "AI_UNAVAILABLE", text, "KIMI", "{}", False)
            self.m.tasks.park(text[:60].strip() or "Voice note", text)  # keep the thought
            self._set_overlay(None)
            self.m.set_error(*(AI_BUDGET if isinstance(e, BudgetExceeded) else AI_GONE))
            self._status("AI_UNAVAILABLE", error=str(e)[:160], transcript=text)
            raise AiUnavailable(str(e)) from e
        self._complete_wake_scripts(planner, plan)
        raw = plan.model_dump_json()
        vid = self.m.device.add_voice_session(key, "DRAFT", text, f"KIMI ({getattr(planner, 'model', '')})", raw,
                                              plan.needs_confirmation)
        result: dict[str, Any] = {"voice_session_id": vid, "transcript": text, "planner_mode": "KIMI",
                                  "plan": json.loads(raw), "committed": None, "activity": activity}
        if source == "voice":
            self._set_overlay(None)
        if auto_commit:
            result["committed"] = self.m.commit_plan(plan, text)
            self.m.device.set_voice_status(vid, "COMMITTED")
        self._status("DONE" if auto_commit else "DRAFT", voice_session_id=vid, transcript=text, planner_mode="KIMI")
        return result
