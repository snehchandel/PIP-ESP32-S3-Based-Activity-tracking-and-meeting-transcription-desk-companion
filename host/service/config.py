"""Settings: environment / .env via pydantic-settings, Kimi key in the OS keyring (D13), user
preferences edited from the dashboard in data/settings.json (never in .env)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
KEYRING_SERVICE = "pip-companion"
KEYRING_USER = "MOONSHOT_API_KEY"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    moonshot_api_key: str = ""
    moonshot_base_url: str = "https://api.moonshot.ai/v1"
    moonshot_model: str = "kimi-k2-0905-preview"

    pip_host_port: int = 18421
    pip_db_path: str = str(ROOT / "data" / "pip.db")
    pip_timezone: str = "America/Toronto"
    pip_transport: str = "auto"  # auto (USB board, re-probed) | usb | sim | none
    pip_serial_port: str = ""
    pip_sim_addr: str = "127.0.0.1:18422"

    pip_stt_model: str = "small.en"
    pip_stt_preload: bool = True
    pip_piper_voice: str = ""
    pip_voices_dir: str = str(ROOT / "data" / "voices")
    pip_prefs_path: str = str(ROOT / "data" / "settings.json")
    pip_use_keyring: bool = True  # tests set this False so they never touch the real credential store
    pip_weather: bool = True  # outdoor weather via open-meteo.com (tests disable)

    # ---- API key ---------------------------------------------------------------------------
    def api_key(self) -> str:
        if self.moonshot_api_key:
            return self.moonshot_api_key
        if not self.pip_use_keyring:
            return ""
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
        except Exception:  # keyring backend unavailable
            return ""

    def api_key_source(self) -> str:
        if self.moonshot_api_key:
            return "env"
        return "keyring" if self.api_key() else "none"

    def set_api_key(self, key: str | None) -> None:
        """Store (or with None, delete) the key in Windows Credential Manager / OS keyring."""
        if not self.pip_use_keyring:
            raise RuntimeError("keyring disabled")
        import keyring

        if key:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            except keyring.errors.PasswordDeleteError:
                pass

    # ---- dashboard preferences ---------------------------------------------------------------
    def prefs(self) -> dict[str, Any]:
        p = Path(self.pip_prefs_path)
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (OSError, ValueError):
            return {}

    def save_prefs(self, **updates: Any) -> dict[str, Any]:
        data = {**self.prefs(), **{k: v for k, v in updates.items() if v is not None}}
        p = Path(self.pip_prefs_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def piper_voice(self) -> str:
        return str(self.prefs().get("piper_voice") or self.pip_piper_voice)


@lru_cache
def get_settings() -> Settings:
    return Settings()
