"""Spoken wake-up alarms: pre-render the ~30 s script with Piper, then at ring time play
  1. the device's own alarm chime, 2. the spoken script on PIP's speaker, 3. chimes for 1 minute,
stopping the moment the alarm is dismissed (on PIP or in the app)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from .. import errors
from ..device.voice_out import speak_on_device

if TYPE_CHECKING:
    from ..services import Services

log = logging.getLogger("pip.alarm_audio")
CHIME_ALARM = 4
CHIME_PERIOD_S = 2.5
CHIME_FOR_S = 60.0
WAKE_PACE = 1.12  # slightly slower, softer delivery for wake-ups
RING_LEAD_S = 1.5  # let the device's own alarm chime finish before speaking
AFTER_SPEECH_S = 0.6


class AlarmAudio:
    def __init__(self, svc: Services, cache_dir: Path) -> None:
        self.svc = svc
        self.cache_dir = cache_dir

    def _script(self, a: dict[str, Any]) -> str:
        return str(a.get("tts_script") or f"It's {a['local_hhmm']}. {a['title']}. Time to get up.")

    def _path(self, a: dict[str, Any]) -> Path:
        key = hashlib.sha1(f"{a.get('voice')}|{self._script(a)}".encode()).hexdigest()[:10]
        return self.cache_dir / f"{a['id']}-{key}.pcm"

    def render(self, a: dict[str, Any]) -> Path | None:
        """Synthesize once at creation time (Piper runs ~4x faster than real time on this PC)."""
        if not self.svc.tts.enabled:
            return None
        p = self._path(a)
        if not p.exists():
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            pcm = self.svc.tts.synthesize_pcm(self._script(a), a.get("voice"), WAKE_PACE)
            p.write_bytes(pcm.astype("<i2").tobytes())
            log.info("rendered wake-up speech for %s (%.1f s)", a["id"], pcm.size / 16000)
        return p

    def load(self, a: dict[str, Any]) -> np.ndarray:
        p = self.render(a)
        if p is None:
            return np.zeros(0, dtype=np.int16)
        return np.frombuffer(p.read_bytes(), dtype="<i2")

    def _ringing(self, aid: str) -> bool:
        r = self.svc.manager.ringing
        return bool(r and r["id"] == aid)

    async def ring_sequence(self, aid: str) -> None:
        link = self.svc.link
        try:
            await asyncio.sleep(RING_LEAD_S)  # the device plays its own alarm chime on ALARM_TRIGGER
            a = self.svc.manager.alarms.get(aid)
            if a and a.get("audio_mode") == "TTS" and self.svc.tts.enabled and link.linked and self._ringing(aid):
                pcm = await asyncio.to_thread(self.load, a)
                await speak_on_device(link, pcm, keep_going=lambda: self._ringing(aid))
                await asyncio.sleep(AFTER_SPEECH_S)
            loop = asyncio.get_running_loop()
            end = loop.time() + CHIME_FOR_S
            while self._ringing(aid) and link.linked and loop.time() < end:
                link.play_chime(CHIME_ALARM)
                await asyncio.sleep(CHIME_PERIOD_S)
        except Exception as e:  # never let audio problems block dismissal; log for diagnosis
            errors.report(self.svc.db, "alarm", "Alarm audio failed", str(e), e, alarm_id=aid)
