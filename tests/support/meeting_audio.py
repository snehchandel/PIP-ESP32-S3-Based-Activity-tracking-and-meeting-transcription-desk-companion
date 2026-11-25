"""TEST SUPPORT ONLY: synthetic meetings (Piper voices talking in turns) and a scripted speech-to-text double
that returns the known segment timings, so speaker detection is tested on real voices without Whisper."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host"))

VOICES_DIR = ROOT / "data" / "voices"
LINES = [
    "Okay everyone, let's get started with the weekly sync.",
    "Thanks. I finished the migration script yesterday and it is running on staging now.",
    "Great. Did you see any errors in the logs overnight?",
    "Just one timeout around three in the morning, I think it was the backup job.",
    "I can look into that today. I also need the budget numbers for the third quarter.",
    "Sure, I will send the spreadsheet after lunch.",
    "Let's also decide who presents to the client on Friday.",
    "I can do it if someone helps me with the slides.",
    "I will help with the slides, send me the outline tonight.",
    "Perfect. Next item is the hiring plan for the support team.",
    "We have two candidates for the final round next week.",
    "Okay. Please book the interviews and share the calendar invite.",
]


def piper_available(*voices: str) -> bool:
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return all((VOICES_DIR / f"{v}.onnx").exists() for v in voices)


_TTS: Any = None


def synth_meeting(voices: list[str], lines: list[str] | None = None, gap_s: float = 0.6,
                  seed: int = 1) -> tuple[bytes, list[tuple[float, float, str, int]]]:
    """PCM16 mono 16 kHz of the lines spoken in turn by `voices`, plus truth (start, end, text, voice index)."""
    global _TTS
    from service.speech.tts import TextToSpeech

    if _TTS is None:
        _TTS = TextToSpeech("", VOICES_DIR)
    rng = np.random.default_rng(seed)
    parts, truth, t = [], [], 0.0
    for i, line in enumerate(lines or LINES):
        v = i % len(voices)
        pcm = _TTS.synthesize_pcm(line, voice=voices[v]).astype(np.float32) * float(0.5 + 0.3 * rng.random())
        dur = len(pcm) / 16000
        truth.append((t, t + dur, line, v))
        parts += [pcm, np.zeros(int(gap_s * 16000), np.float32)]
        t += dur + gap_s
    audio = np.concatenate(parts) + rng.normal(0, 80, sum(len(p) for p in parts)).astype(np.float32)  # room noise
    return np.clip(audio, -32768, 32767).astype("<i2").tobytes(), truth


class ScriptedSegmentsSTT:  # test-only double; production uses service.speech.stt.SpeechToText
    """Returns the scripted (start, end, text) segments that fall inside the audio it is given."""
    status = "TEST"

    def __init__(self, segments: list[tuple[float, float, str]]) -> None:
        self.segments = segments
        self.calls = 0

    def transcribe_segments(self, audio: Any, on_segment: Any = None, beam_size: int = 1) -> list[tuple[float, float, str]]:
        self.calls += 1
        dur = len(audio) / 16000
        out = [(a, b, t) for a, b, t in self.segments if b <= dur + 0.05]
        for _, b, _ in out:
            if on_segment:
                on_segment(b)
        return out

    def unload(self) -> None:
        pass
