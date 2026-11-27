"""Neural speaker embeddings ("voiceprints") for speaker detection (ADR-038).

The MFCC + pitch features of diarize.py told people apart poorly across rooms and days: on the user's 7 real
meetings the same-person / different-person equal error rate was 28 %, so one voice often became 2-3 "speakers".
A speaker-verification network trained on thousands of voices maps every stretch of speech to a vector whose
direction is the voice, nearly independent of the words, loudness and microphone distance.

Runs on the CPU with onnxruntime (already a dependency through faster-whisper and Piper): no torch, nothing leaves
the PC. The model file (pinned URL + SHA-256, like the GPU pack) is downloaded once into <data>/models/speaker; the
front-end (log-mel features the network was trained on) is plain numpy. If the model is missing and cannot be
fetched, diarize.py falls back to its MFCC features - a stored embedding's length says which kind it is.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import httpx
import numpy as np

from .. import paths

log = logging.getLogger("pip.voice_embed")
SR = 16000
WINDOW_S = 10.0  # longer stretches: mean of 10 s windows
MIN_S = 0.5


@dataclass(frozen=True)
class SpeakerModel:
    file: str
    url: str
    sha256: str
    size: int
    dim: int
    frontend: str  # "kaldi" (WeSpeaker / 3D-Speaker) or "nemo" (TitaNet)
    scale: float = 1.0  # kaldi front-end: samples are scaled by this before the fbank (WeSpeaker: int16 range)


_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
MODELS = {
    "titanet": SpeakerModel("nemo_en_titanet_large.onnx", _BASE + "nemo_en_titanet_large.onnx",
                            "d51abcf31717ef28162f26acb9d44dd4127c3d44c9b8624f699f3425daca8e77",
                            101_405_493, 192, "nemo"),
    "campplus": SpeakerModel("3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx",
                             _BASE + "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx",
                             "98daf9bcf1c8abf3db374fec4c27a5eda7c58705bb3f180d057b085a72a88bb5", 29_596_979, 512,
                             "kaldi"),
    "wespeaker": SpeakerModel("wespeaker_en_voxceleb_resnet34_LM.onnx",
                              _BASE + "wespeaker_en_voxceleb_resnet34_LM.onnx",
                              "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012", 26_530_550, 256, "kaldi",
                              32768.0),
}
DEFAULT = "campplus"


# ---------------------------------------------------------------- front-ends
@cache
def _kaldi_mel(n_mels: int = 80, nfft: int = 512, low: float = 20.0, high: float = 8000.0) -> np.ndarray:
    def mel(f: np.ndarray | float) -> np.ndarray:
        return 1127.0 * np.log(1.0 + np.asarray(f) / 700.0)
    nbins = nfft // 2
    fft_mel = mel(np.arange(nbins) * SR / nfft)
    lo, hi = float(mel(low)), float(mel(high))
    step = (hi - lo) / (n_mels + 1)
    fb = np.zeros((n_mels, nbins + 1))
    for m in range(n_mels):
        left, center, right = lo + m * step, lo + (m + 1) * step, lo + (m + 2) * step
        fb[m, :nbins] = np.maximum(0.0, np.minimum((fft_mel - left) / (center - left),
                                                   (right - fft_mel) / (right - center)))
    return fb


def kaldi_fbank(x: np.ndarray, scale: float = 1.0) -> np.ndarray:
    """Kaldi-compatible 80-bin log fbank (25 ms / 10 ms, povey window, no dither) with mean normalisation."""
    x = x.astype(np.float64) * scale
    if len(x) < 400:
        x = np.pad(x, (0, 400 - len(x)))
    fr = np.lib.stride_tricks.sliding_window_view(x, 400)[::160].copy()
    fr -= fr.mean(axis=1, keepdims=True)
    fr[:, 1:] -= 0.97 * fr[:, :-1].copy()
    fr[:, 0] -= 0.97 * fr[:, 0]
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(400) / 399)) ** 0.85
    spec = np.abs(np.fft.rfft(fr * win, 512)) ** 2
    feat = np.log(np.maximum(spec @ _kaldi_mel().T, np.finfo(np.float32).eps))
    return (feat - feat.mean(axis=0)).astype(np.float32)


@cache
def _slaney_mel(n_mels: int = 80, nfft: int = 512, fmax: float = 8000.0) -> np.ndarray:
    f_sp, min_log_hz = 200.0 / 3, 1000.0
    min_log_mel, logstep = min_log_hz / f_sp, np.log(6.4) / 27.0

    def hz2mel(f: float) -> float:
        return min_log_mel + np.log(f / min_log_hz) / logstep if f >= min_log_hz else f / f_sp

    def mel2hz(m: np.ndarray) -> np.ndarray:
        return np.where(m >= min_log_mel, min_log_hz * np.exp(logstep * (m - min_log_mel)), f_sp * m)

    fft_f = np.linspace(0, SR / 2, nfft // 2 + 1)
    hz = mel2hz(np.linspace(0.0, hz2mel(fmax), n_mels + 2))
    fdiff = np.diff(hz)
    ramps = hz[:, None] - fft_f[None, :]
    w = np.maximum(0, np.minimum(-ramps[:-2] / fdiff[:-1, None], ramps[2:] / fdiff[1:, None]))
    return w * (2.0 / (hz[2:] - hz[:-2]))[:, None]


def nemo_mel(x: np.ndarray) -> np.ndarray:
    """NeMo's AudioToMelSpectrogramPreprocessor (80 slaney mels, 25 ms hann in a 512 FFT, per-feature norm)."""
    x = x.astype(np.float64)
    x = np.append(x[:1], x[1:] - 0.97 * x[:-1])
    x = np.pad(x, (256, 256))
    fr = np.lib.stride_tricks.sliding_window_view(x, 512)[::160]
    win = np.zeros(512)
    win[56:456] = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(400) / 399)
    spec = np.abs(np.fft.rfft(fr * win, 512)) ** 2
    feat = np.log(spec @ _slaney_mel().T + 2.0 ** -24).T
    feat = (feat - feat.mean(axis=1, keepdims=True)) / (feat.std(axis=1, ddof=1, keepdims=True) + 1e-5)
    return feat.astype(np.float32)


# ---------------------------------------------------------------- the embedder
class VoiceEmbedder:
    def __init__(self, model: SpeakerModel, folder: Path, client: Callable[[], httpx.Client] | None = None) -> None:
        self.model = model
        self._client = client or (lambda: httpx.Client(timeout=httpx.Timeout(30.0, read=120.0),
                                                       follow_redirects=True))
        self.path = folder / model.file
        self._session = None
        self._lock = threading.Lock()

    @property
    def dim(self) -> int:
        return self.model.dim

    def available(self) -> bool:
        return self.path.exists() and self.path.stat().st_size == self.model.size

    def fetch(self) -> bool:
        """Download the model once (pinned size + SHA-256). False when offline or the file does not match."""
        if self.available():
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".part")
        try:
            digest = hashlib.sha256()
            with self._client() as c, c.stream("GET", self.model.url) as r, tmp.open("wb") as f:
                r.raise_for_status()
                for chunk in r.iter_bytes(1 << 20):
                    digest.update(chunk)
                    f.write(chunk)
            if tmp.stat().st_size != self.model.size or (self.model.sha256 and
                                                         digest.hexdigest() != self.model.sha256):
                raise ValueError("the downloaded speaker model does not match its checksum")
            tmp.replace(self.path)
            log.info("speaker model %s downloaded", self.model.file)
            return True
        except Exception as e:
            log.warning("speaker model unavailable (%s) - using MFCC features", e)
            tmp.unlink(missing_ok=True)
            return False

    def _sess(self):  # noqa: ANN202 - onnxruntime is imported lazily
        if self._session is None:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 4
            opts.log_severity_level = 3
            self._session = ort.InferenceSession(str(self.path), opts, providers=["CPUExecutionProvider"])
        return self._session

    def _one(self, audio: np.ndarray) -> np.ndarray:
        s = self._sess()
        if self.model.frontend == "nemo":
            f = nemo_mel(audio)[None]
            out = s.run(["embs"], {"audio_signal": f, "length": np.array([f.shape[2]], dtype=np.int64)})[0]
        else:
            f = kaldi_fbank(audio, self.model.scale)[None]
            out = s.run(None, {s.get_inputs()[0].name: f})[0]
        e = out[0].astype(np.float64)
        return e / max(float(np.linalg.norm(e)), 1e-9)

    def embed(self, audio: np.ndarray) -> np.ndarray | None:
        """Unit-length voiceprint of one stretch of speech (float32 mono 16 kHz), or None if too short."""
        if len(audio) < int(MIN_S * SR):
            return None
        step = int(WINDOW_S * SR)
        parts = [audio[i:i + step] for i in range(0, len(audio), step)]
        parts = [p for p in parts if len(p) >= SR] or [audio]
        with self._lock:
            v = np.mean([self._one(p) for p in parts], axis=0)
        return v / max(float(np.linalg.norm(v)), 1e-9)


_shared: dict[str, VoiceEmbedder] = {}


def embedder(name: str = DEFAULT, folder: Path | None = None) -> VoiceEmbedder:
    """The shared embedder for a model; its file lives in <data>/models/speaker."""
    folder = folder or paths.data_dir() / "models" / "speaker"
    key = f"{name}|{folder}"
    if key not in _shared:
        _shared[key] = VoiceEmbedder(MODELS[name], folder)
    return _shared[key]
