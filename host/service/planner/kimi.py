"""KimiPlanner: Moonshot OpenAI-compatible chat completions with strict local validation.

Malformed output is retried exactly once with the validation errors appended; a second failure
raises PlannerError and the caller must not mutate any state."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from .schema import PlannerOutputV1

SYSTEM_PROMPT = """You are PIP, a calm ADHD focus companion. Turn the user's brain dump into JSON only.
Rules (hard constraints):
- intent is one of CREATE_TASK, MORNING_PLAN, CONTROL_COMMAND, ADD_REMINDER, ADD_ALARM, RESCHEDULE_ITEM,
  QUERY_STATE, NO_ACTION, NEEDS_CLARIFICATION.
- Exactly ONE active_task. Unrelated thoughts go to "parked" with source_text = the user's words.
- active_task.steps: 3-6 steps. Step 1: is_starter=true, duration_min 2-5, a concrete PHYSICAL action
  (e.g. "Open a blank doc and type the title"), never "think about"/"plan"/"consider".
  Other steps: duration_min 5-25, is_starter=false.
- If the dump is too vague for 3 concrete steps: intent=NEEDS_CLARIFICATION with a short clarification_question.
- Times: due_local is "YYYY-MM-DDTHH:MM" in the user's local zone. Vague times ("afternoon", "later",
  "Friday") must set needs_confirmation=true.
- Calm, kind, no shame language.
Return JSON matching this schema: {schema}"""


class PlannerError(RuntimeError):
    pass


class KimiPlanner:
    mode = "KIMI"

    def __init__(self, api_key: str, base_url: str, model: str, tz: str = "America/Toronto",
                 client: httpx.Client | None = None, timeout: float = 45.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.tz = ZoneInfo(tz)
        self.client = client or httpx.Client(timeout=timeout)

    def _call(self, messages: list[dict[str, str]]) -> str:
        r = self.client.post(f"{self.base_url}/chat/completions",
                             headers={"Authorization": f"Bearer {self.api_key}"},
                             json={"model": self.model, "messages": messages, "temperature": 0.3,
                                   "response_format": {"type": "json_object"}})
        if r.status_code >= 400:
            raise PlannerError(f"Kimi HTTP {r.status_code}")
        try:
            return str(r.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, ValueError) as e:
            raise PlannerError("Kimi response missing content") from e

    def plan(self, text: str, now: datetime | None = None) -> PlannerOutputV1:
        now = now or datetime.now(self.tz)
        schema = json.dumps(PlannerOutputV1.model_json_schema(), separators=(",", ":"))
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(schema=schema)},
            {"role": "user", "content": f"Now: {now.strftime('%A %Y-%m-%d %H:%M')} ({self.tz.key}).\n"
                                        f"Brain dump: {text}"},
        ]
        content = self._call(messages)
        try:
            return PlannerOutputV1.model_validate_json(content)
        except ValidationError as first:
            messages += [{"role": "assistant", "content": content},
                         {"role": "user", "content": "Your JSON failed validation. Fix ONLY these errors and "
                                                     f"return the full corrected JSON:\n{first.errors()}"}]
        content = self._call(messages)
        try:
            return PlannerOutputV1.model_validate_json(content)
        except ValidationError as second:
            raise PlannerError(f"Kimi output invalid after retry: {second.error_count()} errors") from second
