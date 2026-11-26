"""faster-whisper speech-to-text (D10): lazy model load, CUDA when usable, else CPU int8."""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

from .. import paths

log = logging.getLogger("pip.stt")


CUDA_PARTS = ("cublas", "cudnn", "cuda_nvrtc")


def cuda_dll_dirs() -> list[str]:
    """Folders holding the CUDA 12 cuBLAS + cuDNN 9 DLLs: the pip wheels (development venv) and the GPU speech pack
    the packaged app downloads (speech/gpu_pack.py)."""
    bases: list[str] = []
    try:
        import nvidia  # namespace package from the wheels

        bases += list(getattr(nvidia, "__path__", []))
    except ImportError:
        pass
    bases.append(str(paths.gpu_pack_dir()))
    return [d for b in bases for sub in CUDA_PARTS if os.path.isdir(d := os.path.join(b, sub, "bin"))]


def _add_cuda_dlls() -> None:
    """faster-whisper (CTranslate2 4.x) needs CUDA 12 cuBLAS + cuDNN 9 for the GPU. On Windows they come as pip
    wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12) whose DLLs sit in site-packages/nvidia/*/bin - not on the DLL
    search path, so CUDA fell back to the CPU ("cublas64_12.dll is not found"). Put them there before loading."""
    if sys.platform != "win32":
        return
    for dll_dir in cuda_dll_dirs():
        if dll_dir not in os.environ.get("PATH", ""):
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


def _repo_folder(model_name: str) -> str:
    """Hugging Face cache folder name of a faster-whisper model ("small.en" -> models--Systran--faster-whisper-small.en)."""
    try:
        from faster_whisper.utils import _MODELS

        repo = _MODELS.get(model_name, model_name)
    except ImportError:
        repo = model_name
    return "models--" + repo.replace("/", "--")


def model_root(model_name: str) -> Path | None:
    """PIP's own models folder (packaged app). On first use a model the PC already has in the Hugging Face cache is
    copied there instead of downloaded again. None = development: use the Hugging Face cache as before."""
    root = paths.models_dir()
    if root is None:
        return None
    target = root / _repo_folder(model_name)
    if not (target / "snapshots").is_dir():
        try:
            from huggingface_hub import constants

            cached = Path(constants.HF_HUB_CACHE) / _repo_folder(model_name)
            if (cached / "snapshots").is_dir():
                log.info("copying Whisper %s from the Hugging Face cache", model_name)
                shutil.copytree(cached, target, dirs_exist_ok=True)
        except Exception as e:  # nothing to copy, or the copy failed: download instead
            log.info("no cached Whisper %s to copy: %s", model_name, e)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _folder_mb(path: Path) -> int:
    try:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) // 1_000_000
    except OSError:
        return 0


class SpeechToText:
    def __init__(self, model_name: str = "small.en") -> None:
        self.model_name = model_name
        self._model: Any = None
        self._lock = threading.Lock()
        self.device = ""
        self.loading = False
        self.error = ""
        self.vocabulary: list[str] = []  # names/acronyms the user says (Settings): passed to Whisper as hotwords
        self._downloading = False
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
            root = paths.models_dir()
            if self._downloading and root is not None:
                mb = _folder_mb(root / _repo_folder(self.model_name))
                return f"DOWNLOADING ({self.model_name}, {mb} MB so far)"
            return f"LOADING ({self.model_name})"
        return f"NOT_LOADED ({self.model_name})"

    def _load(self) -> Any:
        with _LOAD_LOCK:
            return self._load_locked()

    def _load_locked(self) -> Any:
        import numpy as np
        from faster_whisper import WhisperModel

        root = model_root(self.model_name)
        if root is not None and not (root / _repo_folder(self.model_name) / "snapshots").is_dir():
            self._downloading = True  # first use of this model in the packaged app: fetched from Hugging Face
        for device, compute in (("cuda", "float16"), ("cpu", "int8")):
            if device in _DEVICE_FAILED:
                continue
            try:
                model = WhisperModel(self.model_name, device=device, compute_type=compute,
                                     download_root=str(root) if root else None)
                self._downloading = False
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
        self._downloading = False
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
