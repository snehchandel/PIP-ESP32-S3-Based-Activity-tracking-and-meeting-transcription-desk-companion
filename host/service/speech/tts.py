"""Text-to-speech: Piper when binary + voice model are configured, else structured built-in chimes."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class TextToSpeech:
    def __init__(self, piper_bin: str = "", voice: str = "") -> None:
        self.piper = piper_bin or shutil.which("piper") or ""
        self.voice = voice
        self.enabled = bool(self.piper and Path(self.piper).exists() and voice and Path(voice).exists())

    @property
    def mode(self) -> str:
        return "PIPER" if self.enabled else "CHIME"

    @property
    def status(self) -> str:
        return f"Piper ({Path(self.voice).name})" if self.enabled else "Built-in Chime (Piper not configured)"

    def synthesize(self, text: str) -> bytes:
        """Return 16-bit mono WAV bytes. Only valid when mode == PIPER."""
        if not self.enabled:
            raise RuntimeError("Piper TTS not configured")
        r = subprocess.run([self.piper, "--model", self.voice, "--output_file", "-"], input=text.encode(),
                           capture_output=True, timeout=30, check=True)
        return r.stdout
