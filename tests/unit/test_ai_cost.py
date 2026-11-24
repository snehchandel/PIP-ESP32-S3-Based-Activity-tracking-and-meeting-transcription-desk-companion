"""Kimi cost meter: per-call pricing (cache hits are cheaper), daily/monthly totals, and the monthly cap."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from service.ai_cost import CostMeter
from service.config import Settings
from service.main import create_app
from service.planner import BudgetExceeded
from service.storage.db import Database


def _settings(tmp_path, **kw):  # type: ignore[no-untyped-def]
    return Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                    pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"), **kw)


def test_cost_uses_cached_rate_and_caps(tmp_path) -> None:  # type: ignore[no-untyped-def]
    m = CostMeter(Database(":memory:"), _settings(tmp_path))
    # k3.1-pro: 2000 fresh in * $2 + 1000 cached * $0.20 + 400 out * $10 per million
    usd = m.record("kimi-k3.1-pro", "plan", {"prompt_tokens": 3000, "cached_tokens": 1000, "completion_tokens": 400})
    assert usd == pytest.approx((2000 * 2 + 1000 * 0.2 + 400 * 10) / 1e6)
    s = m.summary(7)
    assert s["today"]["calls"] == 1 and s["month"]["cost_usd"] == pytest.approx(usd, abs=1e-4)
    assert len(s["days"]) == 7 and s["cap_state"] == "OK"
    m.check_budget()  # no cap: fine
    m.set_cap(usd * 1.1)
    assert m.summary()["cap_state"] == "WARN"
    m.record("kimi-k3.1-pro", "plan", {"prompt_tokens": 3000, "completion_tokens": 400,
                                       "prompt_tokens_details": {"cached_tokens": 1000}})
    with pytest.raises(BudgetExceeded):
        m.check_budget()
    m.set_cap(None)
    m.check_budget()
    m.set_price("kimi-k3.1-pro", {"input": 1, "cached": 0.1, "output": 5})
    assert m.price("kimi-k3.1-pro")["output"] == 5
    assert m.price("kimi-unknown")["output"] == 15.0  # unknown models are priced conservatively


def test_planning_is_metered_and_stopped_by_the_cap(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from tests.support.fake_kimi import FakeKimi
    kimi = FakeKimi()
    try:
        with TestClient(create_app(_settings(tmp_path, moonshot_api_key="sk-test-fake-0000",
                                             moonshot_base_url=kimi.base_url))) as c:
            assert c.post("/api/v1/tasks/plan", json={"text": "Write the report", "auto_commit": True}).status_code == 200
            u = c.get("/api/v1/ai/usage").json()
            assert u["month"]["calls"] >= 1 and u["month"]["cost_usd"] > 0 and u["active_model"] == "kimi-k3.1-pro"
            c.put("/api/v1/ai/budget", json={"monthly_cap_usd": 0.0001})
            r = c.post("/api/v1/tasks/plan", json={"text": "Another thing", "auto_commit": True})
            assert r.status_code == 503
            st = c.get("/api/v1/state").json()
            assert st["error"]["title"] == "AI budget reached"
            assert c.post("/api/v1/alarms/script", json={"title": "Gym"}).status_code == 429
            assert c.put("/api/v1/ai/budget", json={"monthly_cap_usd": None}).json()["cap_usd"] is None
    finally:
        kimi.close()
