"""Text-to-speech with Piper (offline neural TTS). Falls back to built-in device chimes if no voice is installed.

Voices are .onnx models (+ .onnx.json) in data/voices/ or a path set in Settings."""
from __future__ import annotations

import io
import logging
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("pip.tts")
DEVICE_RATE = 16000


def find_voice(configured: str, voices_dir: Path) -> Path | None:
    if configured and Path(configured).exists():
        return Path(configured)
    found = sorted(voices_dir.glob("*.onnx")) if voices_dir.exists() else []
    return found[0] if found else None


def resample(pcm: np.ndarray, src_rate: int, dst_rate: int = DEVICE_RATE) -> np.ndarray:
    """Linear resample int16 mono audio (good enough for speech on a small speaker)."""
    if src_rate == dst_rate or pcm.size == 0:
        return pcm.astype(np.int16)
    n_out = int(round(pcm.size * dst_rate / src_rate))
    x_old = np.linspace(0.0, 1.0, num=pcm.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, pcm.astype(np.float32)).astype(np.int16)


class TextToSpeech:
    def __init__(self, voice_path: str = "", voices_dir: Path | None = None) -> None:
        self.voices_dir = voices_dir or Path("data/voices")
        self.voice_path = find_voice(voice_path, self.voices_dir)
        self._voice: Any = None
        self._extra: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.error = ""
        try:
            import piper  # noqa: F401
            self.installed = True
        except ImportError:
            self.installed = False

    @property
    def enabled(self) -> bool:
        return self.installed and self.voice_path is not None

    @property
    def mode(self) -> str:
        return "PIPER" if self.enabled else "CHIME"

    @property
    def status(self) -> str:
        if not self.installed:
            return "Built-in Chime (piper-tts not installed)"
        if self.voice_path is None:
            return "Built-in Chime (no Piper voice in data/voices)"
        if self.error:
            return f"Piper error: {self.error}"
        return f"Piper ({self.voice_path.stem})" + (" ready" if self._voice else "")

    def set_voice(self, path: str) -> None:
        with self._lock:
            self.voice_path = find_voice(path, self.voices_dir)
            self._voice = None
            self.error = ""

    def voices(self) -> list[str]:
        return [p.stem for p in sorted(self.voices_dir.glob("*.onnx"))] if self.voices_dir.exists() else []

    def voice_file(self, name: str | None) -> Path | None:
        if name:
            p = self.voices_dir / f"{name}.onnx"
            if p.exists():
                return p
        return self.voice_path

    def _load(self, path: Path | None = None) -> Any:
        from piper import PiperVoice

        path = path or self.voice_path
        assert path is not None
        if path == self.voice_path:
            if self._voice is None:
                self._voice = PiperVoice.load(str(path))
            return self._voice
        if str(path) not in self._extra:
            self._extra[str(path)] = PiperVoice.load(str(path))
        return self._extra[str(path)]

    def synthesize_pcm(self, text: str, voice: str | None = None, length_scale: float | None = None) -> np.ndarray:
        """Mono int16 PCM at 16 kHz, ready for the device speaker. `voice` = a voice name in data/voices;
        length_scale > 1 speaks slower (used for calm, warm wake-up messages)."""
        if not self.enabled:
            raise RuntimeError("Piper voice not configured")
        from piper import SynthesisConfig

        with self._lock:
            try:
                v = self._load(self.voice_file(voice))
                cfg = SynthesisConfig(length_scale=length_scale) if length_scale else None
                parts, rate = [], DEVICE_RATE
                for chunk in v.synthesize(text, syn_config=cfg):
                    rate = chunk.sample_rate
                    parts.append(np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16))
            except Exception as e:  # model load / onnxruntime failure
                self.error = str(e)[:120]
                log.warning("piper synthesis failed: %s", e)
                raise
        pcm = np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)
        return resample(pcm, rate)

    def synthesize_wav(self, text: str, voice: str | None = None, length_scale: float | None = None) -> bytes:
        pcm = self.synthesize_pcm(text, voice, length_scale)
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(DEVICE_RATE)
            w.writeframes(pcm.tobytes())
        return out.getvalue()
