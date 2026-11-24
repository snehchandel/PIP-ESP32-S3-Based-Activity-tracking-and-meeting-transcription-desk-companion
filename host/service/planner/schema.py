"""PlannerOutputV1: the strict contract every planner (Kimi or local) must satisfy (spec section 2)."""
from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class IntentType(str, Enum):
    CREATE_TASK = "CREATE_TASK"
    MORNING_PLAN = "MORNING_PLAN"
    CONTROL_COMMAND = "CONTROL_COMMAND"
    ADD_REMINDER = "ADD_REMINDER"
    ADD_ALARM = "ADD_ALARM"
    RESCHEDULE_ITEM = "RESCHEDULE_ITEM"
    QUERY_STATE = "QUERY_STATE"
    NO_ACTION = "NO_ACTION"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


ABSTRACT_STARTERS = re.compile(r"^\s*(think|consider|reflect|plan|decide|figure|brainstorm|ponder|get ready)\b", re.I)


HEADER_LIKE = re.compile(r"^\s*(#|step\s*\d|phase\b|part\s*\d|section\b|stage\b|preparation\s*:|setup\s*:)|:\s*$", re.I)


class Step(BaseModel):
    title: str = Field(min_length=3, max_length=96)
    duration_min: int = Field(ge=1, le=60)
    is_starter: bool = False

    @model_validator(mode="after")
    def not_a_header(self) -> Step:
        if HEADER_LIKE.search(self.title) or (self.title.isupper() and len(self.title) > 4):
            raise ValueError(f"step '{self.title}' looks like a heading, not a concrete action")
        return self


class ActiveTask(BaseModel):
    title: str = Field(min_length=2, max_length=64)
    short_title: str | None = Field(default=None, max_length=24)  # fits the 400x300 device header
    steps: list[Step]
    if_then_cue: str | None = None

    @model_validator(mode="after")
    def adhd_invariants(self) -> ActiveTask:
        if not 3 <= len(self.steps) <= 6:
            raise ValueError(f"active task needs 3-6 micro-steps, got {len(self.steps)}")
        first = self.steps[0]
        if not first.is_starter or not 2 <= first.duration_min <= 5:
            raise ValueError("step 1 must be a 2-5 minute starter (is_starter=true)")
        if ABSTRACT_STARTERS.match(first.title):
            raise ValueError(f"starter must be a concrete physical action, not '{first.title}'")
        for s in self.steps[1:]:
            if s.is_starter:
                raise ValueError("only step 1 may be a starter")
            if not 5 <= s.duration_min <= 25:
                raise ValueError(f"step '{s.title}' must be 5-25 minutes")
        return self


class ScheduledItem(BaseModel):
    kind: Literal["REMINDER", "ALARM", "TASK"]
    title: str = Field(min_length=2, max_length=64)
    when_text: str = ""
    due_local: str | None = None  # ISO local datetime "YYYY-MM-DDTHH:MM"
    needs_confirmation: bool = False
    repeat_days: str | None = Field(default=None, pattern=r"^(MO|TU|WE|TH|FR|SA|SU)(,(MO|TU|WE|TH|FR|SA|SU))*$")


class ParkedItem(BaseModel):
    title: str = Field(min_length=2, max_length=64)
    source_text: str


class ControlCommand(BaseModel):
    action: Literal["START", "PAUSE", "RESUME", "BREAK", "RESET", "COMPLETE_STEP", "SPLIT_STEP"]


class PlannerOutputV1(BaseModel):
    version: Literal[1] = 1
    intent: IntentType
    active_task: ActiveTask | None = None
    scheduled: list[ScheduledItem] = Field(default_factory=list)
    parked: list[ParkedItem] = Field(default_factory=list)
    control: ControlCommand | None = None
    clarification_question: str | None = None
    needs_confirmation: bool = False
    summary: str = ""

    @model_validator(mode="after")
    def consistent(self) -> PlannerOutputV1:
        if self.intent == IntentType.NEEDS_CLARIFICATION and not self.clarification_question:
            raise ValueError("NEEDS_CLARIFICATION requires clarification_question")
        if self.intent == IntentType.CREATE_TASK and self.active_task is None:
            raise ValueError("CREATE_TASK requires active_task")
        if self.intent == IntentType.CONTROL_COMMAND and self.control is None:
            raise ValueError("CONTROL_COMMAND requires control")
        if any(s.needs_confirmation for s in self.scheduled):
            self.needs_confirmation = True
        return self


PLANNER_JSON_SCHEMA = PlannerOutputV1.model_json_schema()
