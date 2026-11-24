"""REST: Kimi cost meter (tokens + dollars per day) and the optional monthly cap."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .routes_core import svc

router = APIRouter(prefix="/api/v1")


@router.get("/ai/usage")
def usage(req: Request, days: int = 30) -> dict[str, Any]:
    s = svc(req)
    out = s.cost.summary(max(1, min(days, 120)))
    try:
        out["active_model"] = s.kimi_model() if s.settings.api_key() else None
    except Exception:
        out["active_model"] = None
    return out


class BudgetIn(BaseModel):
    monthly_cap_usd: float | None = Field(default=None, ge=0, le=10_000)  # null/0 = no cap


@router.put("/ai/budget")
def set_budget(body: BudgetIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    s.cost.set_cap(body.monthly_cap_usd)
    s.db.log("INFO", "settings", f"AI monthly cap set to {body.monthly_cap_usd or 'none'}")
    return usage(req)


class PriceIn(BaseModel):
    model: str = Field(min_length=3, max_length=80)
    input: float = Field(ge=0, le=1000)   # USD per million tokens
    cached: float = Field(ge=0, le=1000)
    output: float = Field(ge=0, le=1000)


@router.put("/ai/prices")
def set_price(body: PriceIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    s.cost.set_price(body.model, {"input": body.input, "cached": body.cached, "output": body.output})
    return usage(req)
