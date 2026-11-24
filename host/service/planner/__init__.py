"""TaskPlanner interface + factory. Kimi is the only production planner (user decision, ADR-013).

LocalRulePlanner remains as a library module (time parsing tests, step templates) but is never used to
silently replace Kimi: if Kimi is unavailable the device shows "AI has left the device"."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .kimi import BudgetExceeded, KimiPlanner, PlannerError, UsageSink, resolve_model
from .local_rule import LocalRulePlanner
from .schema import IntentType, PlannerOutputV1


class TaskPlanner(Protocol):
    mode: str

    def plan(self, text: str, now: datetime | None = None, activity: str = "BRAIN_DUMP") -> PlannerOutputV1: ...


def make_planner(api_key: str, base_url: str, model: str, tz: str, on_usage: UsageSink | None = None) -> KimiPlanner:
    """Raises PlannerError when no key is configured."""
    return KimiPlanner(api_key, base_url, model, tz, on_usage=on_usage)


__all__ = ["BudgetExceeded", "IntentType", "KimiPlanner", "LocalRulePlanner", "PlannerError", "PlannerOutputV1", "TaskPlanner",
           "make_planner", "resolve_model"]
