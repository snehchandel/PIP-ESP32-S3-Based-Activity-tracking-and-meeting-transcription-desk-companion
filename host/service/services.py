"""Service container: wires storage, state, planner, speech, alarms, device link and the WS hub."""
from __future__ import annotations

import asyncio
import logging

from .alarms.scheduler import AlarmScheduler
from .api.ws import WsHub
from .config import Settings
from .device.link import DeviceLink, make_transport
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
        self.tts = TextToSpeech(settings.pip_piper_bin, settings.pip_piper_voice)
        self.voice = VoicePipeline(self.manager, self.stt, self.planner, self.hub.publish)
        if transport == "config":
            transport = make_transport(settings.pip_transport, settings.pip_sim_addr, settings.pip_serial_port)
        self.link = DeviceLink(self.manager, transport if not isinstance(transport, str) else None, self.voice,
                               self.hub.publish)
        self.alarm_scheduler = AlarmScheduler(self.manager)
        self._ticker: asyncio.Task[None] | None = None

    def planner(self) -> TaskPlanner:
        s = self.settings
        return make_planner(s.api_key(), s.moonshot_base_url, s.moonshot_model, s.pip_timezone)

    @property
    def planner_mode(self) -> str:
        return "KIMI" if self.settings.api_key() else "LOCAL_RULE"

    async def start(self) -> None:
        self.hub.bind(asyncio.get_running_loop())
        await self.link.start()
        self._ticker = asyncio.create_task(self._tick_alarms())

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
