"""Where PIP's files live - from the repository (development) or from the packaged app (PIP.exe, ADR-034).

Two kinds of files:
  * resources: shipped with the app, read only (desktop UI, SQL migrations, icon, bundled firmware).
    Repository: the checkout itself. Packaged: the PyInstaller bundle folder (sys._MEIPASS).
  * user data: database, settings, logs, voices, meetings, Whisper models, the GPU speech pack.
    Repository: <repo>/data (as always). Packaged: %LOCALAPPDATA%/PIP. PIP_DATA_DIR overrides both.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
REPO_ROOT = Path(__file__).resolve().parents[2]


def resource_root() -> Path:
    """Folder holding the read-only files that ship with PIP."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return REPO_ROOT


def app_dir() -> Path:
    """Folder of the running program (PIP.exe when packaged, the repository otherwise)."""
    return Path(sys.executable).parent if FROZEN else REPO_ROOT


def data_dir() -> Path:
    """The user's PIP data folder."""
    env = os.environ.get("PIP_DATA_DIR", "").strip()
    if env:
        return Path(env)
    if FROZEN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "PIP"
    return REPO_ROOT / "data"


def ui_dist() -> Path:
    """The built companion app (React)."""
    return resource_root() / ("ui" if FROZEN else "host/desktop_ui/dist")


def bundled_firmware() -> Path:
    """Firmware image the Device -> Firmware updater offers as 'latest build'."""
    if FROZEN:
        return resource_root() / "firmware" / "pip_firmware.bin"
    return REPO_ROOT / "firmware" / "build" / "pip_firmware.bin"


def icon_path() -> Path:
    return resource_root() / ("pip.ico" if FROZEN else "tools/pip.ico")


def env_file() -> Path:
    """Optional .env (development: repository root; packaged: the data folder)."""
    return data_dir() / ".env" if FROZEN else REPO_ROOT / ".env"


def logs_dir() -> Path:
    return data_dir() / "logs"


def models_dir() -> Path | None:
    """Where faster-whisper keeps its models. None = the Hugging Face cache (development keeps using it)."""
    return data_dir() / "models" if FROZEN else None


def gpu_pack_dir() -> Path:
    """CUDA DLLs downloaded by the GPU speech add-on (speech/gpu_pack.py)."""
    return data_dir() / "gpu"
