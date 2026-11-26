"""faster-whisper speech-to-text (D10): lazy model load, CUDA when usable, else CPU int8."""
from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
from typing import Any

log = logging.getLogger("pip.stt")


def _add_cuda_dlls() -> None:
    """faster-whisper (CTranslate2 4.x) needs CUDA 12 cuBLAS + cuDNN 9 for the GPU. On Windows they come as pip
    wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12) whose DLLs sit in site-packages/nvidia/*/bin - not on the DLL
    search path, so CUDA fell back to the CPU ("cublas64_12.dll is not found"). Put them there before loading."""
    if sys.platform != "win32":
        return
    try:
        import nvidia  # namespace package from the wheels
    except ImportError:
        return
    for base in getattr(nvidia, "__path__", []):
        for sub in ("cublas", "cudnn", "cuda_nvrtc"):
            dll_dir = os.path.join(base, sub, "bin")
            if os.path.isdir(dll_dir) and dll_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
                with contextlib.suppress(OSError):
                    os.add_dll_directory(dll_dir)


_add_cuda_dlls()


# What Whisper "hears" in silence or noise (it was trained on captioned video). Dropped only when Whisper itself
# says the stretch is probably not speech, so a real "Thank you." stays.
_PHANTOMS = {"thank you.", "thank you", "thanks for watching!", "thanks for watching.", "thank you for watching.",
             "please subscribe.", "you", "you.", "bye.", "subtitles by the amara.org community", "so.", "okay."}


def phantom(seg: Any) -> bool:
    nsp = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
    if nsp > 0.6 and float(getattr(seg, "avg_logprob", 0.0) or 0.0) < -0.7:
        return True
    return nsp > 0.4 and str(getattr(seg, "text", "")).strip().lower() in _PHANTOMS


def cuda_usable() -> bool:
    """A CUDA GPU CTranslate2 can see, and no failed CUDA load in this process."""
    if "cuda" in _DEVICE_FAILED:
        return False
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        return False
# Once CUDA has failed in this process, never try it again: a second CUDA attempt after a failed one (missing
# cuBLAS) hung inside ctranslate2 forever, which froze the meeting transcriber's model load.
_DEVICE_FAILED: set[str] = set()
_LOAD_LOCK = threading.Lock()  # one model load at a time (the voice and meeting instances load independently)


class SpeechToText:
    def __init__(self, model_name: str = "small.en") -> None:
        self.model_name = model_name
        self._model: Any = None
        self._lock = threading.Lock()
        self.device = ""
        self.loading = False
        self.error = ""
        self.vocabulary: list[str] = []  # names/acronyms the user says (Settings): passed to Whisper as hotwords
        self.cleanup = True  # voice commands: drop "um"/"uh" and stutters before planning (speech/cleanup.py)
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
        with _LOAD_LOCK:
            return self._load_locked()

    def _load_locked(self) -> Any:
        import numpy as np
        from faster_whisper import WhisperModel

        for device, compute in (("cuda", "float16"), ("cpu", "int8")):
            if device in _DEVICE_FAILED:
                continue
            try:
                model = WhisperModel(self.model_name, device=device, compute_type=compute)
                # CUDA can construct fine yet fail at inference (e.g. cuBLAS DLL missing): prove it works.
                segs, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="en", beam_size=1)
                list(segs)
                self.device = f"{device}/{compute}"
                self.error = ""
                log.info("faster-whisper %s loaded on %s", self.model_name, self.device)
                return model
            except Exception as e:  # CUDA libs missing, no GPU, or offline model fetch failed
                log.info("whisper load on %s failed: %s", device, e)
                if device != "cpu":
                    _DEVICE_FAILED.add(device)
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
            segments, _ = self._model.transcribe(audio, language="en", beam_size=self.beam(), vad_filter=True,
                                                 hotwords=self.hotwords())
            text = " ".join(s.text.strip() for s in segments if not phantom(s)).strip()
            if self.cleanup:
                from .cleanup import clean_text
                text = clean_text(text, self.vocabulary)
            return text

    def beam(self) -> int:
        """Beam search on the GPU (measured: cleaner sentences, fewer false starts, ~25 % slower); greedy on the CPU,
        where beam 5 would be several times slower."""
        return 5 if self.device.startswith("cuda") else 1

    def hotwords(self) -> str | None:
        return ", ".join(self.vocabulary)[:400] or None

    def transcribe_segments(self, audio: Any, on_segment: Any = None, beam_size: int | None = None) -> list[tuple[float, float, str]]:
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
            segments, _ = self._model.transcribe(audio, language="en", beam_size=beam_size or self.beam(), vad_filter=True,
                                                 vad_parameters={"min_silence_duration_ms": 500},
                                                 condition_on_previous_text=False, hotwords=self.hotwords())
            out = []
            for seg in segments:
                text = seg.text.strip()
                if text and not phantom(seg):
                    out.append((float(seg.start), float(seg.end), text))
                if on_segment:
                    on_segment(float(seg.end))
            return out

    def unload(self) -> None:
        """Free the model's memory (the meeting transcriber does this when its queue is empty)."""
        with self._lock:
            self._model = None
