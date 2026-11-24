"""Service container: wires storage, state, planner, speech, alarms, device link and the WS hub."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from . import errors
from .alarms.audio import AlarmAudio
from .alarms.scheduler import AlarmScheduler
from .api.ws import WsHub
from .config import Settings
from .device.link import DeviceLink, make_transport
from .device.voice_out import speak_on_device
from .planner import PlannerError, TaskPlanner, make_planner, resolve_model
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
            transport = make_transport(settings.pip_transport, settings.pip_sim_addr, settings.pip_serial_port)
        self.link = DeviceLink(self.manager, transport if not isinstance(transport, str) else None, self.voice,
                               self.hub.publish)
        self.alarm_scheduler = AlarmScheduler(self.manager)
        data_dir = Path(settings.pip_db_path).parent if settings.pip_db_path != ":memory:" else Path(settings.pip_voices_dir).parent
        self.alarm_audio = AlarmAudio(self, data_dir / "alarm_audio")
        self.manager.voice_for_style = self.alarm_voice
        self.weather = WeatherService(settings, self.manager)
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
        s = self.settings
        return make_planner(s.api_key(), s.moonshot_base_url, self.kimi_model(), s.pip_timezone)

    def alarm_voice(self, style: str) -> str | None:
        """Piper voice for a spoken alarm: the user's choice in Settings, else the best installed one."""
        style = "male" if style == "male" else "female"
        installed = {p.stem for p in Path(self.settings.pip_voices_dir).glob("*.onnx")}
        pref = self.settings.prefs().get(f"alarm_voice_{style}")
        for name in [pref, *ALARM_VOICES[style]]:
            if name and name in installed:
                return str(name)
        return None

    @property
    def planner_mode(self) -> str:
        return "KIMI" if self.settings.api_key() else "AI_NOT_CONFIGURED"

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.hub.bind(self.loop)
        await self.link.start()
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
            except Exception:
                log.exception("alarm check failed")
            await asyncio.sleep(1.0)
