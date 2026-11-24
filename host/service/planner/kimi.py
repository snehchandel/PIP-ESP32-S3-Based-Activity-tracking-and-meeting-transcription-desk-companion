"""KimiPlanner: Moonshot chat completions with strict local validation (the only planner for voice/brain dumps).

Malformed output is retried once with the validation errors appended; a second failure, an HTTP error,
a timeout or a missing key raises PlannerError and the caller shows "AI has left the device"."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from .schema import PlannerOutputV1

# Newest first; the first one the account actually offers is used unless the user picks one in Settings.
# Standard (non-"highspeed") models only: highspeed variants cost several times more per token.
PREFERRED_MODELS = ["kimi-k3.1-pro", "kimi-k3", "kimi-k2.6", "kimi-k2-0905-preview"]
EXPENSIVE_MARKERS = ("highspeed", "turbo")


def is_expensive(model: str) -> bool:
    return any(k in model for k in EXPENSIVE_MARKERS)

ACTIVITY_RULES = {
    "BRAIN_DUMP": "The user is brain-dumping. Pick ONE task to act on now (active_task); everything unrelated goes to "
                  "parked; anything with a time goes to scheduled.",
    "CALENDAR": "The user is talking about their calendar. Prefer scheduled items (kind TASK or REMINDER) with due_local. "
                "Only create an active_task if they explicitly want to start something now.",
    "FOCUS": "The user is in a focus session. Prefer intent CONTROL_COMMAND (START, PAUSE, RESUME, BREAK, COMPLETE_STEP, "
             "SPLIT_STEP) when they ask to control the timer/step; otherwise park the thought so focus isn't broken.",
    "ALARMS": "The user wants alarms. Use scheduled items with kind ALARM and due_local; for repeating alarms set "
              "repeat_days like MO,WE,FR. intent ADD_ALARM.",
}

ALARM_RULES = """Alarm rules (kind ALARM):
- title is a SHORT label (max 24 chars) like "Gym wake-up" - never the user's whole sentence.
- If the user wants the alarm to talk, speak, say something, use a voice, or describes a voice
  ("lady voice", "female voice", "a guy's voice"...): use_voice=true, voice_style "female" or "male"
  (default "female"), and write `script`: 70-90 words (about 30 seconds spoken) in second person,
  warm, upbeat and encouraging, personalised to why they're getting up (include any words they asked for),
  ending with a gentle "time to get up". Plain sentences, no emojis, no stage directions."""

SYSTEM_PROMPT = """You are PIP, a calm ADHD focus companion. Reply with ONE JSON object only (no markdown, no list).
{activity}
How to break a task into steps (hard rules):
- Steps are the concrete physical/real-world actions THIS user must do, taken from their own words and situation.
  Example: "I need to send my tax papers to the accountant" ->
  "Open the folder with this year's tax papers", "Scan the T4 and receipts with your phone",
  "Attach the scans to an email to the accountant", "Send it and file the papers back".
- NEVER output headings, phases or categories as steps (no "Preparation:", "Step 1", "Phase 2", "Setup", ALL CAPS).
- NEVER use generic filler ("work on the task", "write down the first action", "review progress").
- 3-6 steps. Step 1: is_starter=true, 2-5 min, the tiniest physical first move. Other steps 5-25 min.
- Each step title is an imperative sentence of at most 40 characters.
- active_task.title max 40 chars; active_task.short_title max 18 chars for a tiny screen (e.g. "Gym bag + keys").
- If too vague for concrete steps: intent NEEDS_CLARIFICATION with a short clarification_question.
- Times: due_local "YYYY-MM-DDTHH:MM" in the user's local zone. Vague times ("afternoon", "later", "Friday")
  set needs_confirmation=true.
- Kind, calm language. No shame.
{alarm_rules}
JSON schema: {schema}"""


class PlannerError(RuntimeError):
    pass


class BudgetExceeded(PlannerError):
    """The optional monthly AI spending cap (Settings) has been reached."""


UsageSink = Callable[[str, str, dict[str, Any]], None]  # (model, purpose, usage) -> None


def resolve_model(client: httpx.Client, base_url: str, api_key: str, preferred: str = "") -> str:
    """Pick the configured model if the account has it, else the newest preferred one it offers."""
    r = client.get(f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
    if r.status_code != 200:
        raise PlannerError(f"Kimi /models HTTP {r.status_code}")
    available: list[str] = [str(m.get("id", "")) for m in r.json().get("data", [])]
    for m in ([preferred] if preferred else []) + PREFERRED_MODELS:
        if m in available:
            return m
    kimi = [m for m in available if m.startswith("kimi") and not is_expensive(m)]
    if not kimi:
        raise PlannerError("no Kimi chat model available for this key")
    return str(sorted(kimi)[-1])


def extract_json(content: str) -> str:
    """Models sometimes wrap the object in ```json fences or a one-element list."""
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", content.strip(), flags=re.M).strip()
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        return m.group(0) if m else text
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        return json.dumps(data[0])
    return text


class KimiPlanner:
    mode = "KIMI"

    def __init__(self, api_key: str, base_url: str, model: str, tz: str = "America/Toronto",
                 client: httpx.Client | None = None, timeout: float = 90.0, on_usage: UsageSink | None = None) -> None:
        if not api_key:
            raise PlannerError("no Kimi API key configured")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.tz = ZoneInfo(tz)
        self.client = client or httpx.Client(timeout=timeout)
        self.on_usage = on_usage

    def _post(self, messages: list[dict[str, str]], purpose: str, json_mode: bool) -> httpx.Response:
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = self.client.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}"},
                             json=body)
        if r.status_code < 400 and self.on_usage:
            try:
                usage = r.json().get("usage") or {}
                if usage:
                    self.on_usage(self.model, purpose, usage)
            except (ValueError, AttributeError):
                pass
        return r

    def _call(self, messages: list[dict[str, str]], purpose: str = "plan") -> str:
        try:
            r = self._post(messages, purpose, json_mode=True)
        except httpx.HTTPError as e:  # timeout, DNS, connection reset...
            raise PlannerError(f"Kimi unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:
            detail = ""
            try:
                err = r.json().get("error", "")
                detail = str(err.get("message", "") if isinstance(err, dict) else err)[:160]
            except (ValueError, AttributeError):
                pass
            raise PlannerError(f"Kimi HTTP {r.status_code} {detail}".strip())
        try:
            return str(r.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, ValueError) as e:
            raise PlannerError("Kimi response missing content") from e

    def wake_script(self, title: str, note: str = "") -> str:
        """~30 s (70-90 words) of warm spoken wake-up encouragement for a voice alarm."""
        try:
            r = self._post([{"role": "system", "content": "Write a spoken wake-up message of 70-90 words "
                             "(about 30 seconds aloud), second person, warm, upbeat and encouraging, ending "
                             "with a gentle 'time to get up'. Plain sentences only: no emojis, no stage "
                             "directions, no quotes, no title."},
                            {"role": "user", "content": f"Alarm: {title}. {note}".strip()}], "wake_script", json_mode=False)
        except httpx.HTTPError as e:
            raise PlannerError(f"Kimi unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise PlannerError(f"Kimi HTTP {r.status_code}")
        text = str(r.json()["choices"][0]["message"]["content"]).strip().strip('"')
        if len(text.split()) < 30:
            raise PlannerError("Kimi returned a script that is too short")
        return text[:1200]

    def plan(self, text: str, now: datetime | None = None, activity: str = "BRAIN_DUMP") -> PlannerOutputV1:
        now = now or datetime.now(self.tz)
        schema = json.dumps(PlannerOutputV1.model_json_schema(), separators=(",", ":"))
        rules = ACTIVITY_RULES.get(activity, ACTIVITY_RULES["BRAIN_DUMP"])
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(activity=rules, schema=schema, alarm_rules=ALARM_RULES)},
            {"role": "user", "content": f"Now: {now.strftime('%A %Y-%m-%d %H:%M')} ({self.tz.key}).\n"
                                        f"Activity: {activity}\nWhat I said: {text}"},
        ]
        content = self._call(messages)
        try:
            return PlannerOutputV1.model_validate_json(extract_json(content))
        except ValidationError as first:
            messages += [{"role": "assistant", "content": content},
                         {"role": "user", "content": "Your JSON failed validation. Fix ONLY these errors and "
                                                     f"return the full corrected JSON object:\n{first.errors()}"}]
        content = self._call(messages)
        try:
            return PlannerOutputV1.model_validate_json(extract_json(content))
        except ValidationError as second:
            raise PlannerError(f"Kimi output invalid after retry: {second.error_count()} errors") from second
