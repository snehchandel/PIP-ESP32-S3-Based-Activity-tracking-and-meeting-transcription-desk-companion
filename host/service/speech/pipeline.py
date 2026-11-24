"""Voice brain-dump pipeline: device PCM stream -> STT -> planner -> commit/confirmation."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

from ..planner import LocalRulePlanner, PlannerError, PlannerOutputV1, TaskPlanner
from ..state.manager import DeviceStateManager
from .stt import SpeechToText

log = logging.getLogger("pip.voice")
MAX_BYTES = 60 * 16000 * 2  # 60 s of 16 kHz mono PCM


def run_planner(planner: TaskPlanner, fallback: LocalRulePlanner, text: str) -> tuple[PlannerOutputV1, str]:
    try:
        return planner.plan(text), planner.mode
    except PlannerError as e:  # Kimi failed twice or HTTP error: zero mutation, local engine continues
        log.warning("planner %s failed (%s) - using LocalRulePlanner", planner.mode, e)
        return fallback.plan(text), "LOCAL_RULE (Kimi fallback)"


class VoicePipeline:
    def __init__(self, manager: DeviceStateManager, stt: SpeechToText, planner: Callable[[], TaskPlanner],
                 notify: Callable[[str, dict[str, Any]], None]) -> None:
        self.m = manager
        self.stt = stt
        self.planner = planner
        self.fallback = LocalRulePlanner(manager.tz.key)
        self.notify = notify
        self.streams: dict[int, bytearray] = {}
        self.last: dict[str, Any] = {"status": "IDLE"}

    def start(self, stream_id: int) -> None:
        self.streams = {stream_id: bytearray()}
        self._status("LISTENING", stream_id=stream_id)

    def data(self, stream_id: int, pcm: bytes) -> None:
        buf = self.streams.get(stream_id)
        if buf is not None and len(buf) + len(pcm) <= MAX_BYTES:
            buf += pcm

    def end(self, stream_id: int, total_samples: int) -> None:
        pcm = bytes(self.streams.pop(stream_id, b""))
        threading.Thread(target=self._process, args=(stream_id, pcm), daemon=True, name="pip-voice").start()

    def _status(self, status: str, **extra: Any) -> None:
        self.last = {"status": status, **extra}
        self.notify("voice_session_updated", self.last)

    def _set_overlay(self, overlay: str | None, stage: str = "") -> None:
        with self.m.lock:
            self.m.overlay = overlay
            self.m.thinking_stage = stage
            self.m.changed()

    def _process(self, stream_id: int, pcm: bytes) -> None:
        key = f"stream-{stream_id}-{len(pcm)}"
        self._set_overlay("TRANSCRIBING", "Transcribing...")
        self._status("TRANSCRIBING", seconds=round(len(pcm) / 32000, 1))
        try:
            text = self.stt.transcribe(pcm) if pcm else ""
        except Exception as e:
            log.warning("STT failed: %s", e)
            self._set_overlay(None)
            self._status("STT_ERROR", error=str(e)[:160])
            return
        if not text:
            self._set_overlay(None)
            self._status("EMPTY", seconds=round(len(pcm) / 32000, 1))
            return
        self.process_text(text, key, source="voice", auto_commit=True)

    def process_text(self, text: str, key: str, source: str = "text", auto_commit: bool = False) -> dict[str, Any]:
        if source == "voice":
            self._set_overlay("THINKING", "Breaking into steps...")
        plan, mode = run_planner(self.planner(), self.fallback, text)
        raw = plan.model_dump_json()
        vid = self.m.device.add_voice_session(key, "DRAFT", text, mode, raw, plan.needs_confirmation)
        result: dict[str, Any] = {"voice_session_id": vid, "transcript": text, "planner_mode": mode,
                                  "plan": json.loads(raw), "committed": None}
        if source == "voice":
            self._set_overlay(None)
        if auto_commit:
            result["committed"] = self.m.commit_plan(plan, text)
            self.m.device.set_voice_status(vid, "COMMITTED")
        self._status("DONE" if auto_commit else "DRAFT", voice_session_id=vid, transcript=text,
                     planner_mode=mode)
        return result
