"""Settings: environment / .env via pydantic-settings, Kimi key via OS keyring fallback (D13)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    moonshot_api_key: str = ""
    moonshot_base_url: str = "https://api.moonshot.ai/v1"
    moonshot_model: str = "kimi-k2-0905-preview"

    pip_host_port: int = 18421
    pip_db_path: str = str(ROOT / "data" / "pip.db")
    pip_timezone: str = "America/Toronto"
    pip_transport: str = "auto"  # auto | usb | sim | none
    pip_serial_port: str = ""
    pip_sim_addr: str = "127.0.0.1:18422"

    pip_stt_model: str = "small.en"
    pip_piper_bin: str = ""
    pip_piper_voice: str = ""

    def api_key(self) -> str:
        if self.moonshot_api_key:
            return self.moonshot_api_key
        try:
            import keyring

            return keyring.get_password("pip-companion", "MOONSHOT_API_KEY") or ""
        except Exception:  # keyring backend unavailable
            return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
