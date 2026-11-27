"""NVIDIA Parakeet-TDT-0.6B v3 for meeting transcripts (ADR-039): onnxruntime on the CPU, no torch.

Picked over Whisper large-v3-turbo and Qwen3-ASR-1.7B on far-field meeting audio (AMI single distant mic, ADR-038):
34.8 % WER vs 46.3 % (Whisper) and 37.2 % (Qwen3). The full-precision model is used - the int8 one is faster
(23x vs 15x real time on the CPU) but gave back most of the gain (39.5 %).

* Model files (2.5 GB, CC-BY-4.0) come from the ONNX export istupakov/parakeet-tdt-0.6b-v3-onnx at a pinned revision,
  each checked against its pinned size + SHA-256, into <data>/models/parakeet-tdt-0.6b-v3. A copy already in the
  Hugging Face cache is used instead of downloading it again.
* onnx-asr (MIT, numpy only) runs the encoder + TDT decoder and NeMo's mel front-end.
* Long recordings are cut by the Silero VAD faster-whisper ships (0.5 s pauses, chunks of at most 30 s), every
  chunk is transcribed with token times and split into sentences, so a line roughly follows a turn - what the
  speaker detection and the transcript view expect (same (start, end, text) lines as Whisper).
* Same interface as speech.stt.SpeechToText for the meeting worker (transcribe_segments / unload / status /
  vocabulary). If the model cannot be fetched or loaded, the meeting is transcribed with Whisper instead.
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..webclient import download_client

log = logging.getLogger("pip.parakeet")

NAME = "parakeet-tdt-0.6b-v3"
REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
REVISION = "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce"
SR = 16000
MAX_CHUNK_S = 30.0       # VAD chunks are cut at this length (Parakeet handles more; shorter lines suit speakers)
MIN_SENTENCE_S = 1.5     # a sentence shorter than this stays with the next one (voiceprints need some audio)
BATCH = 4                # VAD chunks per encoder run


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int
    sha256: str


FILES = (
    ModelFile("config.json", 97, "666903c76b9798caf2c210afd4f6cd60b08a8dbf9800ec8d7a3bc0d2148ac466"),
    ModelFile("vocab.txt", 93_939, "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d"),
    ModelFile("decoder_joint-model.onnx", 72_520_893,
              "e978ddf6688527182c10fde2eb4b83068421648985ef23f7a86be732be8706c1"),
    ModelFile("encoder-model.onnx", 41_770_866, "98a74b21b4cc0017c1e7030319a4a96f4a9506e50f0708f3a516d02a77c96bb1"),
    ModelFile("encoder-model.onnx.data", 2_435_420_160,
              "9a22d372c51455c34f13405da2520baefb7125bd16981397561423ed32d24f36"),
)
TOTAL_BYTES = sum(f.size for f in FILES)
# A fine-tuned Parakeet exported to ONNX the same way (pip_parakeet_dir) needs at least these files
CUSTOM_FILES = ("config.json", "vocab.txt", "encoder-model.onnx", "decoder_joint-model.onnx")
_SPACE = re.compile(r"\A\s|\s\B|(\s)\b")  # onnx-asr's token joining (vocab pieces carry their leading space)


def join_tokens(tokens: list[str]) -> str:
    return _SPACE.sub(lambda m: " " if m.group(1) else "", "".join(tokens)).strip()


def split_sentences(tokens: list[str], stamps: list[float], start_s: float, end_s: float) -> list[tuple[float, float, str]]:
    """Token pieces with start times (seconds into a chunk starting at start_s) -> sentence lines in meeting time."""
    out: list[tuple[float, float, str]] = []
    cur: list[str] = []
    first = 0.0
    for i, (tok, t) in enumerate(zip(tokens, stamps, strict=True)):
        if not cur:
            first = t
        cur.append(tok)
        nxt = stamps[i + 1] if i + 1 < len(stamps) else None
        if nxt is not None and tok.rstrip().endswith((".", "?", "!")) and nxt - first >= MIN_SENTENCE_S:
            text = join_tokens(cur)
            if text:
                out.append((round(start_s + first, 2), round(start_s + min(nxt, t + 0.6), 2), text))
            cur = []
    if cur and (text := join_tokens(cur)):
        out.append((round(start_s + first, 2), round(end_s, 2), text))
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def _hf_cache_copy(f: ModelFile) -> Path | None:
    """The file from a Hugging Face cache snapshot of the pinned revision, if this PC has one."""
    try:
        from huggingface_hub import constants
        p = Path(constants.HF_HUB_CACHE) / ("models--" + REPO.replace("/", "--")) / "snapshots" / REVISION / f.name
        return p if p.is_file() and p.stat().st_size == f.size else None
    except Exception:
        return None


class ParakeetSTT:
    """Meeting speech-to-text with Parakeet; `fallback()` gives the Whisper engine used when Parakeet can't run."""

    model_name = NAME

    def __init__(self, folder: Path, fallback: Callable[[], Any],
                 client: Callable[[], httpx.Client] | None = None, custom: bool = False) -> None:
        self.folder = folder
        self.custom = custom  # a fine-tuned export the user put there: used as it is, never downloaded or checked
        self.fallback = fallback
        self._client = client or download_client
        self._model: Any = None
        self._lock = threading.Lock()
        self.vocabulary: list[str] = []  # not used by the model; the meeting worker fixes names' case with it
        self.cleanup = True
        self.error = ""
        self.loading = False
        self.done_bytes = 0
        self.downloading = False
        self.using_fallback = False

    # ---- files ----------------------------------------------------------------------------------------------
    def installed(self) -> bool:
        if self.custom:
            return all((self.folder / n).is_file() for n in CUSTOM_FILES)
        return all((self.folder / f.name).is_file() and (self.folder / f.name).stat().st_size == f.size for f in FILES)

    @property
    def label(self) -> str:
        """What made a transcript (stored with the meeting): the stock model, or the fine-tuned folder's name."""
        return f"{NAME}@{self.folder.name}" if self.custom else NAME

    def fetch(self) -> None:
        """Every model file in place and checked: copied from the Hugging Face cache or downloaded. Raises on a
        failed download or a checksum mismatch (the bad file is removed)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        self.done_bytes = 0
        for f in FILES:
            dest = self.folder / f.name
            if dest.is_file() and dest.stat().st_size == f.size:
                self.done_bytes += f.size
                continue
            tmp = dest.with_name(dest.name + ".part")
            before = self.done_bytes
            cached = _hf_cache_copy(f)
            if cached is not None:
                shutil.copyfile(cached, tmp)
            else:
                self.downloading = True
                url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{f.name}"
                with self._client() as c, c.stream("GET", url) as r, tmp.open("wb") as out:
                    r.raise_for_status()
                    for chunk in r.iter_bytes(1 << 20):
                        out.write(chunk)
                        self.done_bytes += len(chunk)
            if tmp.stat().st_size != f.size or _sha256(tmp) != f.sha256:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"{f.name} does not match its checksum")
            tmp.replace(dest)
            self.done_bytes = before + f.size
        self.downloading = False
        log.info("Parakeet model ready in %s", self.folder)

    # ---- engine ---------------------------------------------------------------------------------------------
    @property
    def device(self) -> str:
        """Where speech runs ("cpu"; the Whisper fallback's device while it stands in), like SpeechToText.device."""
        if self.using_fallback:
            return str(getattr(self.fallback(), "device", "") or "")
        return "cpu" if self._model is not None else ""

    @property
    def status(self) -> str:
        if self._model is not None:
            return f"READY ({NAME} on cpu)"
        if self.using_fallback:
            return f"FALLBACK (Whisper; Parakeet: {self.error})"
        if self.downloading:
            return f"DOWNLOADING ({NAME}, {self.done_bytes // 1_000_000} of {TOTAL_BYTES // 1_000_000} MB)"
        if self.loading:
            return f"LOADING ({NAME})"
        if self.error:
            return f"ERROR ({self.error})"
        return f"NOT_LOADED ({NAME})"

    def _load(self) -> Any:
        import onnx_asr
        import onnxruntime as ort

        if not self.installed():
            if self.custom:
                raise RuntimeError(f"fine-tuned model incomplete in {self.folder} (needs {', '.join(CUSTOM_FILES)})")
            self.fetch()
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        return onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", self.folder, sess_options=opts,
                                   providers=["CPUExecutionProvider"]).with_timestamps()

    def _ready(self) -> bool:
        if self._model is not None:
            return True
        self.loading = True
        try:
            self._model = self._load()
            self.error, self.using_fallback = "", False
            return True
        except Exception as e:
            self.error = str(e)[:160]
            self.downloading = False
            log.warning("Parakeet unavailable (%s) - transcribing with Whisper", e)
            return False
        finally:
            self.loading = False

    def transcribe_segments(self, audio: Any, on_segment: Any = None,
                            beam_size: int | None = None) -> list[tuple[float, float, str]]:
        """Timed lines of a long recording (float32 mono 16 kHz)."""
        with self._lock:
            if not self._ready():
                self.using_fallback = True
                return self.fallback().transcribe_segments(audio, on_segment, beam_size)
            if audio.size < 1600:
                return []
            from faster_whisper.vad import VadOptions, get_speech_timestamps

            spans = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500,
                                                            max_speech_duration_s=MAX_CHUNK_S, speech_pad_ms=200))
            out: list[tuple[float, float, str]] = []
            for i in range(0, len(spans), BATCH):
                part = spans[i:i + BATCH]
                results = self._model.recognize([audio[s["start"]:s["end"]] for s in part], sample_rate=SR)
                for s, r in zip(part, results, strict=True):
                    t0, t1 = s["start"] / SR, s["end"] / SR
                    if r.tokens and r.timestamps:
                        out += split_sentences(list(r.tokens), list(r.timestamps), t0, t1)
                    if on_segment:
                        on_segment(t1)
            return out

    def unload(self) -> None:
        """Free the ~3 GB the model holds (the meeting worker does this when it goes idle)."""
        with self._lock:
            self._model = None
        fb = self.fallback() if self.using_fallback else None
        if fb is not None:
            fb.unload()


def default_folder(data_dir: Path) -> Path:
    return data_dir / "models" / NAME


def is_parakeet(name: str) -> bool:
    return name == NAME
