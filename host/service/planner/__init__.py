"""TaskPlanner interface + factory: Kimi when MOONSHOT_API_KEY is set, else the offline LocalRulePlanner."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .kimi import KimiPlanner, PlannerError
from .local_rule import LocalRulePlanner
from .schema import IntentType, PlannerOutputV1


class TaskPlanner(Protocol):
    mode: str

    def plan(self, text: str, now: datetime | None = None) -> PlannerOutputV1: ...


def make_planner(api_key: str, base_url: str, model: str, tz: str) -> TaskPlanner:
    if api_key:
        return KimiPlanner(api_key, base_url, model, tz)
    return LocalRulePlanner(tz)


__all__ = ["IntentType", "KimiPlanner", "LocalRulePlanner", "PlannerError", "PlannerOutputV1", "TaskPlanner",
           "make_planner"]
