"""faster-whisper speech-to-text (D10): lazy model load, CUDA when usable, else CPU int8."""
from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger("pip.stt")


class SpeechToText:
    def __init__(self, model_name: str = "small.en") -> None:
        self.model_name = model_name
        self._model: Any = None
        self._lock = threading.Lock()
        self.device = ""
        self.error = ""
        try:
            import faster_whisper  # noqa: F401
            self.installed = True
        except ImportError:
            self.installed = False

    @property
    def status(self) -> str:
        if not self.installed:
            return "UNAVAILABLE (faster-whisper not installed)"
        if self._model is not None:
            return f"READY ({self.model_name} on {self.device})"
        if self.error:
            return f"ERROR ({self.error})"
        return f"NOT_LOADED ({self.model_name}; loads on first voice capture)"

    def _load(self) -> Any:
        from faster_whisper import WhisperModel

        for device, compute in (("cuda", "float16"), ("cpu", "int8")):
            try:
                model = WhisperModel(self.model_name, device=device, compute_type=compute)
                self.device = f"{device}/{compute}"
                log.info("faster-whisper %s loaded on %s", self.model_name, self.device)
                return model
            except Exception as e:  # CUDA libs missing, no GPU, or offline model fetch failed
                log.info("whisper load on %s failed: %s", device, e)
                self.error = str(e)[:120]
        raise RuntimeError(self.error or "model load failed")

    def transcribe(self, pcm16le: bytes, sample_rate: int = 16000) -> str:
        if not self.installed:
            raise RuntimeError("faster-whisper not installed")
        import numpy as np

        with self._lock:
            if self._model is None:
                self._model = self._load()
                self.error = ""
            audio = np.frombuffer(pcm16le, dtype=np.int16).astype(np.float32) / 32768.0
            if sample_rate != 16000 or audio.size < 1600:
                return ""
            segments, _ = self._model.transcribe(audio, language="en", beam_size=1, vad_filter=True)
            return " ".join(s.text.strip() for s in segments).strip()
