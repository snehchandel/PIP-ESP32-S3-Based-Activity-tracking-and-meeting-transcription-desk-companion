"""Service container: wires storage, state, planner, speech, alarms, device link and the WS hub."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .alarms.scheduler import AlarmScheduler
from .api.ws import WsHub
from .config import Settings
from .device.link import DeviceLink, make_transport
from .device.voice_out import speak_on_device
from .planner import TaskPlanner, make_planner
from .speech.pipeline import VoicePipeline
from .speech.stt import SpeechToText
from .speech.tts import TextToSpeech
from .state.manager import DeviceStateManager
from .storage.db import Database
from .transport import DeviceTransport

log = logging.getLogger("pip.services")


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
        self._ticker: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    def planner(self) -> TaskPlanner:
        s = self.settings
        return make_planner(s.api_key(), s.moonshot_base_url, s.moonshot_model, s.pip_timezone)

    @property
    def planner_mode(self) -> str:
        return "KIMI" if self.settings.api_key() else "LOCAL_RULE"

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.hub.bind(self.loop)
        await self.link.start()
        self._ticker = asyncio.create_task(self._tick_alarms())
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
        if kind != "alarm_triggered" or not self.loop:
            return
        r = self.manager.ringing
        if r and r.get("audio_mode") == "TTS" and self.tts.enabled:
            text = r.get("tts_script") or f"It's {r['hhmm']}. {r['title']}."
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._speak_after_chime(text)))

    async def _speak_after_chime(self, text: str) -> None:
        await asyncio.sleep(1.5)  # let the device alarm chime finish first
        try:
            await self.speak(text)
        except Exception:
            log.exception("alarm speech failed")

    async def stop(self) -> None:
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
