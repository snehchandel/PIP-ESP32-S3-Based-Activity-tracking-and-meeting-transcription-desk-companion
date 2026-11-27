"""Test double for meetings.voice_embed.VoiceEmbedder: the "voice" of a stretch of audio is its dominant tone.

Lets the service plumbing (neural voiceprints, the one-time upgrade of old meetings, remembered voices) be tested
without the 100 MB speaker model: tones of different pitch are different people, the same pitch is the same one."""
from __future__ import annotations

import numpy as np

SR = 16000


class ToneVoiceprints:
    dim = 8

    def __init__(self) -> None:
        self.embedded = 0

    def fetch(self) -> bool:
        return True

    def available(self) -> bool:
        return True

    def embed(self, audio: np.ndarray) -> np.ndarray | None:
        if len(audio) < SR // 2:
            return None
        self.embedded += 1
        hz = float(np.argmax(np.abs(np.fft.rfft(audio)))) * SR / len(audio)
        v = np.zeros(self.dim)
        k = round(hz / 100.0) % self.dim
        v[k] = 1.0
        v[(k + 1) % self.dim] = 0.05
        return v / np.linalg.norm(v)


def tone_meeting(pitches: list[float], line_s: float = 2.0, gap_s: float = 0.5,
                 seed: int = 0) -> tuple[bytes, list[tuple[float, float, str]]]:
    """PCM16 of one tone per line (a little noise on top) and the transcript lines (start, end, text)."""
    rng = np.random.default_rng(seed)
    parts, segs, t = [], [], 0.0
    for i, hz in enumerate(pitches):
        n = int(line_s * SR)
        tone = 0.3 * np.sin(2 * np.pi * hz * np.arange(n) / SR) + rng.normal(0, 0.01, n)
        parts += [tone, np.zeros(int(gap_s * SR))]
        segs.append((round(t, 2), round(t + line_s, 2), f"Line {i + 1}."))
        t += line_s + gap_s
    pcm = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype("<i2").tobytes()
    return pcm, segs
