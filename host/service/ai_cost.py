"""Kimi cost meter: every API call's tokens are priced and stored; Settings shows tokens and dollars per day,
month-to-date spend, and enforces an optional monthly cap (warn at 80 %, stop planning at 100 %).

Prices are USD per million tokens and editable in Settings because Moonshot changes them; the defaults are
the published list prices as of Nov 2026 (kimi-k3.1-pro $2 in / $0.20 cached / $10 out)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .planner import BudgetExceeded
from .storage.db import Database

DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "kimi-k3.1-pro": {"input": 2.00, "cached": 0.20, "output": 10.00},
    "kimi-k3.1-pro-highspeed": {"input": 4.00, "cached": 0.40, "output": 20.00},  # cached rate assumed 10 % of input
    "kimi-k3": {"input": 3.00, "cached": 0.30, "output": 15.00},
}
FALLBACK = {"input": 3.00, "cached": 0.30, "output": 15.00}  # unknown model: assume the pricier tier
WARN_AT = 0.8


def cached_tokens(usage: dict[str, Any]) -> int:
    """Moonshot reports cache hits either top-level or OpenAI-style under prompt_tokens_details."""
    details = usage.get("prompt_tokens_details") or {}
    return int(usage.get("cached_tokens") or details.get("cached_tokens") or 0)


class CostMeter:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.s = settings
        self.tz = ZoneInfo(settings.pip_timezone)

    # ---- prices & cap ------------------------------------------------------------------------
    def prices(self) -> dict[str, dict[str, float]]:
        custom = self.s.prefs().get("ai_prices") or {}
        return {**DEFAULT_PRICES, **{k: dict(v) for k, v in custom.items()}}

    def price(self, model: str) -> dict[str, float]:
        if model.startswith("local/"):  # the local AI (meeting summaries on this PC): tokens counted, never billed
            return {"input": 0.0, "cached": 0.0, "output": 0.0}
        return self.prices().get(model, FALLBACK)

    def cap(self) -> float | None:
        v = self.s.prefs().get("ai_monthly_cap_usd")
        return float(v) if v not in (None, "", 0) else None

    def set_cap(self, usd: float | None) -> None:
        # save_prefs ignores None, so store 0 for "no cap"
        self.s.save_prefs(ai_monthly_cap_usd=usd if usd else 0)

    def set_price(self, model: str, p: dict[str, float]) -> None:
        custom = dict(self.s.prefs().get("ai_prices") or {})
        custom[model] = {k: float(p[k]) for k in ("input", "cached", "output")}
        self.s.save_prefs(ai_prices=custom)

    # ---- recording -----------------------------------------------------------------------------
    def cost(self, model: str, prompt: int, cached: int, completion: int) -> float:
        p = self.price(model)
        fresh = max(0, prompt - cached)
        return (fresh * p["input"] + cached * p["cached"] + completion * p["output"]) / 1_000_000

    def record(self, model: str, purpose: str, usage: dict[str, Any]) -> float:
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        cached = min(cached_tokens(usage), prompt)
        usd = self.cost(model, prompt, cached, completion)
        now = datetime.now(UTC)
        with self.db.tx() as c:
            c.execute("INSERT INTO ai_usage(ts_utc,day_local,model,purpose,prompt_tokens,cached_tokens,completion_tokens,"
                      "cost_usd) VALUES (?,?,?,?,?,?,?,?)",
                      (now.isoformat(), now.astimezone(self.tz).date().isoformat(), model, purpose, prompt, cached,
                       completion, usd))
        return usd

    # ---- reporting -------------------------------------------------------------------------------
    def month_spend(self, today: date | None = None) -> float:
        today = today or datetime.now(self.tz).date()
        r = self.db.one("SELECT COALESCE(SUM(cost_usd),0) FROM ai_usage WHERE day_local >= ?",
                        (today.replace(day=1).isoformat(),))
        return float(r[0]) if r else 0.0

    def check_budget(self) -> None:
        cap = self.cap()
        if cap is not None and self.month_spend() >= cap:
            raise BudgetExceeded(f"monthly AI budget of ${cap:.2f} reached")

    def summary(self, days: int = 30) -> dict[str, Any]:
        today = datetime.now(self.tz).date()
        start = today - timedelta(days=days - 1)
        rows = {r["day_local"]: dict(r) for r in self.db.query(
            "SELECT day_local, COUNT(*) calls, SUM(prompt_tokens) prompt, SUM(cached_tokens) cached, "
            "SUM(completion_tokens) completion, SUM(cost_usd) cost FROM ai_usage WHERE day_local >= ? "
            "GROUP BY day_local", (start.isoformat(),))}
        series = []
        for k in range(days):
            d = (start + timedelta(days=k)).isoformat()
            r = rows.get(d, {})
            series.append({"date": d, "calls": int(r.get("calls") or 0), "prompt_tokens": int(r.get("prompt") or 0),
                           "cached_tokens": int(r.get("cached") or 0),
                           "completion_tokens": int(r.get("completion") or 0), "cost_usd": round(float(r.get("cost") or 0), 6)})
        m = self.db.one("SELECT COUNT(*), COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0), "
                        "COALESCE(SUM(cost_usd),0) FROM ai_usage WHERE day_local >= ?",
                        (today.replace(day=1).isoformat(),))
        by_model = [dict(r) for r in self.db.query(
            "SELECT model, COUNT(*) calls, SUM(cost_usd) cost FROM ai_usage WHERE day_local >= ? GROUP BY model "
            "ORDER BY cost DESC", (today.replace(day=1).isoformat(),))]
        spend = float(m[3]) if m else 0.0
        cap = self.cap()
        return {
            "days": series,
            "today": series[-1],
            "month": {"calls": int(m[0]) if m else 0, "prompt_tokens": int(m[1]) if m else 0,
                      "completion_tokens": int(m[2]) if m else 0, "cost_usd": round(spend, 4), "by_model": by_model},
            "cap_usd": cap,
            "cap_used": round(spend / cap, 4) if cap else None,
            "cap_state": ("REACHED" if cap and spend >= cap else "WARN" if cap and spend >= WARN_AT * cap else "OK"),
            "prices": self.prices(),
        }
