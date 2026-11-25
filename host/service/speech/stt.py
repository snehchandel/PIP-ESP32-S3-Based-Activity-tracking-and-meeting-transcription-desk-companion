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
        self.loading = False
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
        if self.loading:
            return f"LOADING ({self.model_name})"
        return f"NOT_LOADED ({self.model_name})"

    def _load(self) -> Any:
        import numpy as np
        from faster_whisper import WhisperModel

        for device, compute in (("cuda", "float16"), ("cpu", "int8")):
            try:
                model = WhisperModel(self.model_name, device=device, compute_type=compute)
                # CUDA can construct fine yet fail at inference (e.g. cuBLAS DLL missing): prove it works.
                segs, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="en", beam_size=1)
                list(segs)
                self.device = f"{device}/{compute}"
                log.info("faster-whisper %s loaded on %s", self.model_name, self.device)
                return model
            except Exception as e:  # CUDA libs missing, no GPU, or offline model fetch failed
                log.info("whisper load on %s failed: %s", device, e)
                self.error = str(e)[:120]
        raise RuntimeError(self.error or "model load failed")

    def preload(self) -> None:
        """Load the model in the background at service start so the first voice capture is instant."""
        if not self.installed or self._model is not None:
            return

        def run() -> None:
            with self._lock:
                if self._model is None:
                    self.loading = True
                    try:
                        self._model = self._load()
                        self.error = ""
                    except Exception as e:
                        log.warning("STT preload failed: %s", e)
                    finally:
                        self.loading = False

        threading.Thread(target=run, name="pip-stt-preload", daemon=True).start()

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

    def transcribe_segments(self, audio: Any, on_segment: Any = None, beam_size: int = 1) -> list[tuple[float, float, str]]:
        """Timed segments of a long recording (float32 mono 16 kHz numpy array). VAD splits at pauses of 0.5 s so
        segments tend to follow turns in a conversation; `on_segment(end_s)` reports progress."""
        if not self.installed:
            raise RuntimeError("faster-whisper not installed")
        with self._lock:
            if self._model is None:
                self._model = self._load()
                self.error = ""
            if audio.size < 1600:
                return []
            segments, _ = self._model.transcribe(audio, language="en", beam_size=beam_size, vad_filter=True,
                                                 vad_parameters={"min_silence_duration_ms": 500},
                                                 condition_on_previous_text=False)
            out = []
            for seg in segments:
                text = seg.text.strip()
                if text:
                    out.append((float(seg.start), float(seg.end), text))
                if on_segment:
                    on_segment(float(seg.end))
            return out

    def unload(self) -> None:
        """Free the model's memory (the meeting transcriber does this when its queue is empty)."""
        with self._lock:
            self._model = None
