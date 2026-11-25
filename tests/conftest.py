from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))

TZ = ZoneInfo("America/Toronto")


@pytest.fixture()
def now() -> datetime:
    return datetime(2026, 11, 23, 10, 0, tzinfo=TZ)  # Monday morning


@pytest.fixture()
def manager():  # type: ignore[no-untyped-def]
    from service.state.manager import DeviceStateManager
    from service.storage.db import Database

    clock = {"t": 1000.0}
    m = DeviceStateManager(Database(":memory:"), "America/Toronto", clock=lambda: clock["t"])
    m._clock = clock  # type: ignore[attr-defined]
    return m


@pytest.fixture(autouse=True)
def _no_real_local_ai(monkeypatch):  # type: ignore[no-untyped-def]
    """Tests never talk to an Ollama that may be running on the developer's PC (a closed port instead)."""
    monkeypatch.setenv("PIP_LOCAL_AI_URL", "http://127.0.0.1:9")
