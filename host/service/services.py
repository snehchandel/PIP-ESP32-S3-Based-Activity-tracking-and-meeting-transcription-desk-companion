"""Service container: wires storage, state, planner, speech, alarms, device link and the WS hub."""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

import httpx

from . import errors
from .ai_cost import CostMeter
from .alarms.audio import AlarmAudio
from .alarms.nudges import NudgeScheduler
from .alarms.scheduler import AlarmScheduler
from .api.ws import WsHub
from .config import Settings
from .device.firmware import FirmwareUpdater
from .device.link import DeviceLink, make_transport
from .device.voice_out import speak_on_device
from .meetings.local_ai import DEFAULT_MODEL as LOCAL_AI_MODEL
from .meetings.local_ai import LocalAI
from .meetings.obsidian import DEFAULT_FOLDER, ObsidianVault
from .meetings.service import SUMMARY_MODES, MeetingService
from .planner import PlannerError, TaskPlanner, make_planner, resolve_model
from .protocol import FrameType
from .speech.pipeline import VoicePipeline
from .speech.stt import SpeechToText
from .speech.tts import TextToSpeech
from .state.manager import DeviceStateManager
from .storage.db import Database
from .transport import DeviceTransport
from .weather import WeatherService

log = logging.getLogger("pip.services")
# Piper voices for spoken wake-ups, best first (only installed ones are used)
ALARM_VOICES = {"female": ["en_GB-jenny_dioco-medium", "en_US-hfc_female-medium", "en_US-lessac-medium"],
                "male": ["en_US-ryan-medium", "en_US-lessac-medium"]}


class Services:
    def __init__(self, settings: Settings, transport: DeviceTransport | None | str = "config") -> None:
        self.settings = settings
        self.db = Database(settings.pip_db_path)
        self.manager = DeviceStateManager(self.db, settings.pip_timezone)
        self.hub = WsHub()
        self.manager.subscribe(self.hub.publish)
        self.stt = SpeechToText(settings.pip_stt_model)
        self.tts = TextToSpeech(settings.piper_voice(), Path(settings.pip_voices_dir))
        self.manager.subscribe(self._on_state_event)
        self.voice = VoicePipeline(self.manager, self.stt, self.planner, self.hub.publish)
        if transport == "config":
            transport = make_transport(settings.pip_transport, settings.pip_sim_addr, settings.pip_serial_port,
                                       wifi_target=lambda: (settings.wifi_hosts(), settings.link_token()))
        self.link = DeviceLink(self.manager, transport if not isinstance(transport, str) else None, self.voice,
                               self.hub.publish)
        self.alarm_scheduler = AlarmScheduler(self.manager)
        data_dir = Path(settings.pip_db_path).parent if settings.pip_db_path != ":memory:" else Path(settings.pip_voices_dir).parent
        self.alarm_audio = AlarmAudio(self, data_dir / "alarm_audio")
        self.manager.voice_for_style = self.alarm_voice
        self.weather = WeatherService(settings, self.manager)
        self.cost = CostMeter(self.db, settings)
        self.link.on_link_up = self._on_link_up
        self.link.on_diag = self._on_diag
        root = Path(__file__).resolve().parents[2]
        self.firmware = FirmwareUpdater(self.link, data_dir, root / "firmware" / "build" / "pip_firmware.bin")
        self.local_ai = LocalAI(settings.pip_local_ai_url, model=self.local_ai_model, on_usage=self.cost.record)
        self.meetings = MeetingService(self.manager, data_dir, settings.pip_meeting_model, self.hub.publish,
                                       summarizer=self.planner, local_ai=self.local_ai,
                                       summary_mode=self.meeting_summary_mode, vault=self.vault,
                                       vocabulary=self.vocabulary, voice_busy=self._voice_busy)
        self.voice.meetings = self.meetings
        self.stt.vocabulary = self.meetings.stt.vocabulary = self.vocabulary()
        self.nudges = NudgeScheduler(self.manager)
        self._ticker: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._model_cache: tuple[object, str] = (None, "")
        errors.setup_error_log(Path(settings.pip_db_path).parent / "logs" if settings.pip_db_path != ":memory:" else None)

    def kimi_model(self) -> str:
        """The configured model if the key offers it, else the newest preferred one (cached per key)."""
        s = self.settings
        key = s.api_key()
        if not key:
            raise PlannerError("no Kimi API key configured")
        wanted = str(s.prefs().get("kimi_model") or "")
        cache_key = (hash(key), wanted)
        if self._model_cache[0] != cache_key:
            with httpx.Client(timeout=15) as c:
                try:
                    model = resolve_model(c, s.moonshot_base_url, key, wanted)
                except httpx.HTTPError as e:
                    raise PlannerError(f"Kimi unreachable: {type(e).__name__}") from e
            self._model_cache = (cache_key, model)
        return self._model_cache[1]

    def planner(self) -> TaskPlanner:
        """Kimi planner that meters every call; raises BudgetExceeded once the monthly cap is spent."""
        s = self.settings
        self.cost.check_budget()
        p = make_planner(s.api_key(), s.moonshot_base_url, self.kimi_model(), s.pip_timezone, on_usage=self.cost.record)
        p.vocabulary = self.vocabulary()
        return p

    # ---- meetings: local AI summaries + Obsidian vault ----------------------------------------------
    def local_ai_model(self) -> str:
        return str(self.settings.prefs().get("local_ai_model") or LOCAL_AI_MODEL)

    def meeting_summary_mode(self) -> str:
        """After each transcription: "local" (default, on this PC), "kimi" (uses the AI budget) or "off"."""
        mode = str(self.settings.prefs().get("meeting_summary") or "local")
        return mode if mode in SUMMARY_MODES else "local"

    def vault(self) -> ObsidianVault | None:
        p = self.settings.prefs()
        root = str(p.get("obsidian_vault") or "").strip()
        if not root or not Path(root).is_dir():
            return None
        return ObsidianVault(Path(root), str(p.get("obsidian_folder") or DEFAULT_FOLDER))

    def _voice_busy(self) -> bool:
        """A voice command is being heard or transcribed (Whisper on the GPU): summaries step aside. The overlay,
        not the open streams, decides: a capture cut off mid-way leaves a stream behind, while the stuck-state
        watchdog always clears the overlay."""
        return self.manager.overlay in ("LISTENING", "TRANSCRIBING")

    def vocabulary(self) -> list[str]:
        v = self.settings.prefs().get("vocabulary") or []
        return [str(w) for w in v if str(w).strip()] if isinstance(v, list) else []

    def set_vocabulary(self, words: list[str]) -> list[str]:
        seen: dict[str, str] = {}
        for w in words:
            w = " ".join(str(w).split())[:40]
            if w and w.lower() not in seen:
                seen[w.lower()] = w
        out = list(seen.values())[:80]
        self.settings.save_prefs(vocabulary=out)
        self.stt.vocabulary = out
        self.meetings.stt.vocabulary = out
        return out

    # ---- device settings pushed over the link ------------------------------------------------
    WAKE_WORDS = {"hiesp": "Hi ESP", "jarvis": "Jarvis", "computer": "Computer", "hijoy": "Hi Joy"}

    def wake_settings(self) -> dict[str, Any]:
        p = self.settings.prefs()
        word = str(p.get("wake_word") or "hiesp")
        return {"enabled": bool(p.get("wake_enabled", True)), "word": word if word in self.WAKE_WORDS else "hiesp"}

    def device_config(self, include_token: bool) -> dict[str, Any]:
        cfg: dict[str, Any] = {"wake": self.wake_settings()}
        if include_token:  # pairing only ever travels over the USB cable
            token = self.settings.link_token(create=True)
            if token:
                cfg["token"] = token.hex()
        return cfg

    def _on_link_up(self, kind: str) -> None:
        self.link.send_json(FrameType.DEVICE_CONFIG, self.device_config(include_token=kind == "USB_HARDWARE"))

    def _on_diag(self, diag: dict[str, Any]) -> None:
        wifi = diag.get("wifi") or {}
        if wifi.get("ip"):
            net = {"ip": wifi["ip"], "host": wifi.get("host", ""), "ssid": wifi.get("ssid", "")}
            if self.settings.prefs().get("device_net") != net:
                self.settings.save_prefs(device_net=net)

    def alarm_voice(self, style: str) -> str | None:
        """Piper voice for a spoken alarm: the user's choice in Settings, else the best installed one."""
        style = "male" if style == "male" else "female"
        installed = {p.stem for p in Path(self.settings.pip_voices_dir).glob("*.onnx")}
        pref = self.settings.prefs().get(f"alarm_voice_{style}")
        for name in [pref, *ALARM_VOICES[style]]:
            if name and name in installed:
                return str(name)
        return None

    def plan_task(self, text: str) -> Any:
        """Kimi breaks one chosen task into concrete steps (ActiveTask, incl. start_local). Raises PlannerError."""
        plan = self.planner().plan(text, activity="TASK")  # type: ignore[call-arg]
        if plan.active_task is None:
            raise PlannerError(plan.clarification_question or "Kimi did not return steps for this")
        return plan.active_task

    def plan_steps(self, text: str) -> tuple[str, str | None, list[dict[str, Any]]]:
        t = self.plan_task(text)
        return t.title, t.short_title, [s.model_dump() for s in t.steps]

    def refine_task_steps(self, tid: str, text: str) -> None:
        """Background: replace a new task's placeholder steps with Kimi's (if it is still untouched)."""
        if not self.settings.api_key():
            return

        def run() -> None:
            try:
                _, _, steps = self.plan_steps(text)
            except Exception as e:  # placeholder steps stay; the user can still edit them
                errors.report(self.db, "planner", "Step refinement failed", str(e), None, task=tid)
                return
            with self.manager.lock:
                if self.manager.device.state().get("active_task_id") == tid:
                    return  # already being worked on: don't pull the steps from under the user
                if self.manager.tasks.replace_open_steps(tid, steps):
                    self.manager.changed("task_refined", task_id=tid)

        threading.Thread(target=run, name="pip-refine", daemon=True).start()

    @property
    def planner_mode(self) -> str:
        return "KIMI" if self.settings.api_key() else "AI_NOT_CONFIGURED"

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.hub.bind(self.loop)
        await self.link.start()
        self.meetings.recover()
        self._ticker = asyncio.create_task(self._tick_alarms())
        self.weather.start()
        if self.settings.pip_stt_preload:
            self.stt.preload()

    # ---- voice output ------------------------------------------------------------------------
    async def speak(self, text: str) -> bool:
        """Synthesize with Piper and play on PIP's speaker. Returns False if not possible."""
        if not self.tts.enabled or not self.link.linked:
            return False
        pcm = await asyncio.to_thread(self.tts.synthesize_pcm, text)
        return await speak_on_device(self.link, pcm)

    def _on_state_event(self, kind: str, payload: dict[str, Any]) -> None:
        if not self.loop:
            return
        if kind == "alarm_triggered" and self.manager.ringing:
            aid = self.manager.ringing["id"]
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.alarm_audio.ring_sequence(aid)))
        elif kind == "items_scheduled":
            ids, ack = list(payload.get("ids", [])), dict(payload.get("ack") or {})
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._after_scheduled(ids, ack)))

    async def _nudge(self, text: str) -> None:
        try:
            if self.link.linked:
                self.link.play_chime(6)  # CONFIRM
                if self.tts.enabled:
                    await asyncio.sleep(0.7)
                    await self.speak(text)
        except Exception as e:
            errors.report(self.db, "nudge", "Nudge failed", str(e), e)

    async def _after_scheduled(self, ids: list[str], ack: dict[str, str]) -> None:
        """Confirm out loud on PIP and pre-render any voice alarm so it plays instantly (even offline)."""
        try:
            if self.link.linked:
                self.link.play_chime(6)  # CONFIRM
                if ack.get("spoken") and self.tts.enabled:
                    await asyncio.sleep(0.7)
                    await self.speak(ack["spoken"])
            for aid in ids:
                a = self.manager.alarms.get(aid)
                if a and a.get("audio_mode") == "TTS":
                    await asyncio.to_thread(self.alarm_audio.render, a)
        except Exception as e:
            errors.report(self.db, "alarm", "Post-scheduling step failed", str(e), e)

    async def stop(self) -> None:
        self.weather.stop()
        if self._ticker:
            self._ticker.cancel()
        await self.link.stop()
        self.db.close()

    async def _tick_alarms(self) -> None:
        while True:
            try:
                self.alarm_scheduler.check()
                self.meetings.tick()
                for text in self.nudges.check():  # reminders due, tasks whose start time came: chime + say it
                    asyncio.ensure_future(self._nudge(text))
            except Exception:
                log.exception("alarm check failed")
            await asyncio.sleep(1.0)
