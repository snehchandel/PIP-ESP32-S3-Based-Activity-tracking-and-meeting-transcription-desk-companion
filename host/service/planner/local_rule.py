"""LocalRulePlanner: deterministic offline brain-dump parser (D10 fallback - a real engine, not a mock).

Pipeline: clause split -> classify (control / query / alarm / reminder / tangent / action) ->
one active lane + parked tangents + scheduled items with explicit ambiguity flags."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from ..calendar.timeparse import parse_when, strip_time_words
from .schema import ActiveTask, ControlCommand, IntentType, ParkedItem, PlannerOutputV1, ScheduledItem, Step
from .step_templates import steps_for

TANGENT = r"(?:also|and also|oh and|plus|btw|by the way|later|remind me|don't forget|dont forget|" \
          r"set (?:an? )?alarm|alarm|wake me)"
SPLIT_RE = re.compile(rf"[.;!?\n]+|,\s*(?:and\s+)?(?={TANGENT}\b)|\s+and\s+(?={TANGENT}\b)|,\s*(?:and\s+)?then\s+",
                      re.I)
FILLER = re.compile(r"^(?:ok(?:ay)?|so|um+|uh+|well|hey pip|pip|i need to|i have to|i should|i want to|i gotta|"
                    r"need to|have to|gotta|let's|lets|also|and also|oh and|plus|btw|by the way|and|then|"
                    r"please|can you|could you)\b[\s,]*", re.I)
VAGUE_TASK = re.compile(r"^(?:stuff|things|something|everything|work|it|that|this|the thing|all the things|"
                        r"do stuff|get stuff done|be productive|do things)$", re.I)
ControlAction = Literal["START", "PAUSE", "RESUME", "BREAK", "RESET", "COMPLETE_STEP", "SPLIT_STEP"]
CONTROL: list[tuple[re.Pattern[str], ControlAction]] = [
           (re.compile(r"\b(pause|hold on|stop the timer)\b", re.I), "PAUSE"),
           (re.compile(r"\b(resume|continue|unpause)\b", re.I), "RESUME"),
           (re.compile(r"\b(start (?:the )?(?:timer|focus|step)|let'?s go|begin)\b", re.I), "START"),
           (re.compile(r"\b(take a break|break time|i need a break)\b", re.I), "BREAK"),
           (re.compile(r"\b(done with (?:this|the) step|finished (?:this|the) step|step done)\b", re.I), "COMPLETE_STEP"),
           (re.compile(r"\b(cut (?:it|this|the step) in half|too big|split (?:it|the step))\b", re.I), "SPLIT_STEP")]
QUERY = re.compile(r"^(?:what(?:'s| is)|whats|when(?:'s| is)|how (?:long|much)|show me|list)\b", re.I)
MORNING = re.compile(r"\b(plan my (?:day|morning)|morning plan|what should i do today|start my day)\b", re.I)


def _clean(clause: str) -> str:
    c = clause.strip(" ,.-")
    prev = None
    while prev != c:
        prev = c
        c = FILLER.sub("", c).strip(" ,.-")
    return c


def _title(text: str, limit: int = 60) -> str:
    t = re.sub(r"\b(?:later|sometime|at some point|whenever)\b", "", text, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,.-")
    t = re.sub(r"^(?:to|for)\s+", "", t, flags=re.I)
    t = re.sub(r"[\s,]+(?:and|or|then|to|for|at|on|by)$", "", t, flags=re.I).strip(" ,.-")
    if len(t) > limit:
        t = t[: limit - 3].rsplit(" ", 1)[0] + "..."
    return t[:1].upper() + t[1:] if t else t


class LocalRulePlanner:
    mode = "LOCAL_RULE"

    def __init__(self, tz: str = "America/Toronto") -> None:
        self.tz = ZoneInfo(tz)

    def plan(self, text: str, now: datetime | None = None, activity: str = "BRAIN_DUMP") -> PlannerOutputV1:
        now = now or datetime.now(self.tz)
        raw = text.strip()
        if not raw:
            return PlannerOutputV1(intent=IntentType.NO_ACTION, summary="Nothing to plan.")
        for pat, action in CONTROL:
            if pat.search(raw) and len(raw.split()) <= 8:
                return PlannerOutputV1(intent=IntentType.CONTROL_COMMAND,
                                       control=ControlCommand(action=action), summary=f"Control: {action.lower()}")
        if MORNING.search(raw):
            return PlannerOutputV1(intent=IntentType.MORNING_PLAN, summary="Here's today's plan.")
        if QUERY.match(raw) and len(raw.split()) <= 10:
            return PlannerOutputV1(intent=IntentType.QUERY_STATE, summary="Showing your current state.")

        active_text: str | None = None
        scheduled: list[ScheduledItem] = []
        parked: list[ParkedItem] = []
        for clause in [c for c in SPLIT_RE.split(raw) if c and c.strip()]:
            low = clause.lower()
            body = _clean(clause)
            if not body:
                continue
            is_alarm = bool(re.search(r"\b(alarm|wake me)\b", low))
            is_reminder = bool(re.search(r"\b(remind me|don't forget|dont forget)\b", low))
            when = parse_when(clause, now, self.tz)
            if is_alarm or is_reminder:
                title = _title(re.sub(r"\b(?:set\s+)?(?:an?\s+)?alarm\b|\bwake me(?: up)?\b|\bremind me(?: to)?\b|"
                                      r"\bdon'?t forget(?: to)?\b|\bfor\b", "", strip_time_words(body), flags=re.I))
                if when is None or when.local is None:
                    if is_alarm:
                        scheduled.append(ScheduledItem(kind="ALARM", title=title or "Alarm", when_text=clause.strip(),
                                                       due_local=None, needs_confirmation=True))
                    else:
                        parked.append(ParkedItem(title=title or _title(body), source_text=clause.strip()))
                    continue
                scheduled.append(ScheduledItem(
                    kind="ALARM" if is_alarm else "REMINDER", title=title or ("Alarm" if is_alarm else "Reminder"),
                    when_text=when.matched_text, due_local=when.local.strftime("%Y-%m-%dT%H:%M"),
                    needs_confirmation=when.needs_confirmation))
                continue
            is_tangent = bool(re.match(rf"\s*,?\s*{TANGENT}\b", clause, re.I)) or "later" in low
            if active_text is None and not is_tangent and when is None:
                active_text = body
            elif when is not None and when.local is not None:
                # a timed clause is a calendar item, never the "do it now" lane
                scheduled.append(ScheduledItem(kind="TASK", title=_title(strip_time_words(body) or body),
                                               when_text=when.matched_text,
                                               due_local=when.local.strftime("%Y-%m-%dT%H:%M"),
                                               needs_confirmation=when.needs_confirmation))
            else:
                ptitle = _title(strip_time_words(body) or body)
                if len(ptitle) >= 2:  # fragments like "M" are speech noise, never a crash (BUG-011)
                    parked.append(ParkedItem(title=ptitle, source_text=clause.strip()))

        if active_text is not None and (VAGUE_TASK.match(active_text) or len(active_text) < 3):
            return PlannerOutputV1(intent=IntentType.NEEDS_CLARIFICATION, scheduled=scheduled, parked=parked,
                                   clarification_question="What's the one thing you want to finish first?",
                                   summary="That's a bit vague - let's pick one thing.")
        if active_text:
            title = _title(active_text, 64)
            steps = steps_for(title)
            starter = str(steps[0]["title"])
            for item in scheduled:  # an untitled alarm/reminder belongs to the focus task
                if item.title in ("Alarm", "Reminder"):
                    item.title = title
            task = ActiveTask(title=title, steps=[Step(**s) for s in steps],  # type: ignore[arg-type]
                              if_then_cue=f"If I sit down at my desk, then I {starter[:1].lower() + starter[1:]}.")
            return PlannerOutputV1(intent=IntentType.CREATE_TASK, active_task=task, scheduled=scheduled, parked=parked,
                                   summary=f"Focus on '{title}' - {len(task.steps)} small steps.")
        if scheduled:
            kind = scheduled[0].kind
            intent = {"ALARM": IntentType.ADD_ALARM, "REMINDER": IntentType.ADD_REMINDER}.get(
                kind, IntentType.RESCHEDULE_ITEM if re.search(r"\b(move|reschedule|push)\b", raw, re.I)
                else IntentType.ADD_REMINDER)
            return PlannerOutputV1(intent=intent,
                                   scheduled=scheduled, parked=parked, summary=f"Added {len(scheduled)} item(s).")
        if parked:
            return PlannerOutputV1(intent=IntentType.NO_ACTION, parked=parked, summary="Parked for later.")
        return PlannerOutputV1(intent=IntentType.NEEDS_CLARIFICATION,
                               clarification_question="What would you like to work on?",
                               summary="I didn't catch a task.")
