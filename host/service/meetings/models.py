"""Local AI models the user can pick for meeting summaries and questions (Settings -> Meetings).

Ollama has no API to browse its online library, so this is a curated list of general chat models that follow a JSON
schema well enough for summaries, small to large. Any other name from ollama.com/library can still be typed in.
Sizes are the default 4-bit downloads (approximate; Ollama reports the exact size while downloading). Each entry is
matched against this PC: fits the GPU (fast), runs on the CPU from RAM (slow but works), or too big.

Reasoning-only models whose thinking can't be switched off (e.g. gpt-oss) are left out: they spend most of their
tokens thinking, which is slow and wasteful for a summary."""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from typing import Any

DEFAULT = "qwen3:8b"
GPU_HEADROOM_GB = 1.5   # context cache + runtime on top of the weights
CPU_FACTOR = 1.6        # RAM needed on the CPU path, as a multiple of the download size

# name, size_gb (download), quality 1-5 for meeting summaries, speed hint, note
CATALOG: list[dict[str, Any]] = [
    {"name": "qwen3:1.7b", "family": "Qwen 3", "params": "1.7B", "size_gb": 1.4, "quality": 1,
     "note": "Tiny and fast; rough summaries, misses action items. Only for very weak PCs."},
    {"name": "llama3.2:3b", "family": "Llama 3.2", "params": "3B", "size_gb": 2.0, "quality": 2,
     "note": "Small and quick on any PC; fine for short meetings."},
    {"name": "qwen3:4b", "family": "Qwen 3", "params": "4B", "size_gb": 2.5, "quality": 3,
     "note": "Best of the small ones; good on a 4 GB GPU or the CPU."},
    {"name": "phi4-mini:3.8b", "family": "Phi-4 mini", "params": "3.8B", "size_gb": 2.5, "quality": 2,
     "note": "Microsoft's small model; good English, weaker on names."},
    {"name": "gemma3:4b", "family": "Gemma 3", "params": "4B", "size_gb": 3.3, "quality": 3,
     "note": "Google's small model; natural summaries."},
    {"name": "mistral:7b", "family": "Mistral", "params": "7B", "size_gb": 4.4, "quality": 3,
     "note": "Older 7B; dependable, a little behind the 8B models."},
    {"name": "llama3.1:8b", "family": "Llama 3.1", "params": "8B", "size_gb": 4.9, "quality": 4,
     "note": "Solid all-rounder; good with long transcripts."},
    {"name": "granite3.3:8b", "family": "Granite 3.3", "params": "8B", "size_gb": 4.9, "quality": 3,
     "note": "IBM's business-tuned model; terse, factual summaries."},
    {"name": "qwen3:8b", "family": "Qwen 3", "params": "8B", "size_gb": 5.2, "quality": 4,
     "note": "Default: best balance on an 8 GB GPU; strong at decisions and action items."},
    {"name": "mistral-nemo:12b", "family": "Mistral NeMo", "params": "12B", "size_gb": 7.1, "quality": 4,
     "note": "Long context; needs ~9 GB of GPU memory to run fast."},
    {"name": "gemma3:12b", "family": "Gemma 3", "params": "12B", "size_gb": 8.1, "quality": 4,
     "note": "Very readable summaries; needs a 10 GB+ GPU."},
    {"name": "phi4:14b", "family": "Phi-4", "params": "14B", "size_gb": 9.1, "quality": 4,
     "note": "Careful and precise; needs a 12 GB GPU."},
    {"name": "qwen3:14b", "family": "Qwen 3", "params": "14B", "size_gb": 9.3, "quality": 5,
     "note": "Noticeably better than 8B; needs a 12 GB GPU."},
    {"name": "mistral-small3.2:24b", "family": "Mistral Small 3.2", "params": "24B", "size_gb": 15.0, "quality": 5,
     "note": "Excellent; needs a 16 GB+ GPU."},
    {"name": "gemma3:27b", "family": "Gemma 3", "params": "27B", "size_gb": 17.0, "quality": 5,
     "note": "Excellent; needs a 20 GB+ GPU."},
    {"name": "qwen3:30b", "family": "Qwen 3 (MoE)", "params": "30B-A3B", "size_gb": 19.0, "quality": 5,
     "note": "Big but fast for its size (only 3B active); 24 GB GPU, or lots of RAM."},
    {"name": "qwen3:32b", "family": "Qwen 3", "params": "32B", "size_gb": 20.0, "quality": 5,
     "note": "Top quality on a 24 GB GPU."},
]


def _ram_gb() -> float:
    try:
        if sys.platform == "win32":
            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MemStatus()
            st.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
            return st.ullTotalPhys / 1024**3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (OSError, ValueError, AttributeError):
        return 0.0


def _nvidia() -> tuple[str, float]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return "", 0.0
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],  # noqa: S603
                             capture_output=True, text=True, timeout=5, check=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return "", 0.0
    best = ("", 0.0)
    for line in out.strip().splitlines():
        name, _, mib = line.rpartition(",")
        try:
            gb = float(mib) / 1024
        except ValueError:
            continue
        if gb > best[1]:
            best = (name.strip(), gb)
    return best


_HW: dict[str, Any] | None = None


def hardware() -> dict[str, Any]:
    """This PC's NVIDIA GPU (name, memory) and RAM, measured once per run."""
    global _HW
    if _HW is None:
        gpu, vram = _nvidia()
        _HW = {"gpu": gpu, "vram_gb": round(vram, 1), "ram_gb": round(_ram_gb(), 1)}
    return _HW


def fit(size_gb: float, hw: dict[str, Any]) -> str:
    """"gpu" (all on the GPU: fast), "mixed" (Ollama splits it between GPU and RAM: works, a few times slower),
    "cpu" (no usable GPU: runs from RAM, slow) or "too_big"."""
    vram, ram = float(hw.get("vram_gb") or 0), float(hw.get("ram_gb") or 0)
    if vram >= size_gb + GPU_HEADROOM_GB:
        return "gpu"
    spare_ram = ram - 6  # leave the OS, the host and Whisper some room
    if vram >= 4 and vram + spare_ram >= size_gb + GPU_HEADROOM_GB and size_gb <= 2 * vram:
        return "mixed"
    if spare_ram + 2 >= size_gb * CPU_FACTOR:
        return "cpu"
    return "too_big"


def same_model(a: str, b: str) -> bool:
    """Ollama calls "mistral" and "mistral:latest" the same model."""
    def norm(n: str) -> str:
        n = n.strip()
        return n if ":" in n else f"{n}:latest"

    return norm(a) == norm(b)


def listing(installed: list[dict[str, Any]], current: str, hw: dict[str, Any]) -> dict[str, Any]:
    """The catalog marked with what is downloaded, what fits this PC and which is recommended, plus downloaded
    models that are not in the catalog. `installed`: Ollama /api/tags entries (name, size in bytes)."""
    names = {m["name"]: m for m in installed}
    rows = []
    for c in CATALOG:
        got = next((n for n in names if same_model(n, c["name"])), None)
        rows.append({**c, "installed": got is not None, "fit": fit(c["size_gb"], hw), "in_use": same_model(c["name"], current),
                     "size_gb": round(names[got]["size"] / 1024**3, 1) if got and names[got].get("size") else c["size_gb"]})
    # recommend the best model that runs fully on the GPU; without one, a small model (an 8B on a CPU takes ~10 min
    # for an hour of meeting)
    pool = ([r for r in rows if r["fit"] == "gpu"] or [r for r in rows if r["fit"] in ("cpu", "mixed") and r["size_gb"] <= 3.5]
            or [r for r in rows if r["fit"] != "too_big"])
    rec = max(pool, key=lambda r: (r["quality"], r["name"] == DEFAULT, -r["size_gb"]))["name"] if pool else None
    for r in rows:
        r["recommended"] = r["name"] == rec
    others = [{"name": n, "size_gb": round((m.get("size") or 0) / 1024**3, 1), "in_use": same_model(n, current),
               "fit": fit((m.get("size") or 0) / 1024**3, hw)}
              for n, m in names.items() if not any(same_model(n, c["name"]) for c in CATALOG)]
    return {"catalog": rows, "other_installed": sorted(others, key=lambda o: o["name"]), "recommended": rec,
            "hardware": hw, "current": current}
