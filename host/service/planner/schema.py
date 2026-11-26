"""PlannerOutputV1: the strict contract every planner (Kimi or local) must satisfy (spec section 2)."""
from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
# generic filler that fits any task: a step must name the real action, object or place
GENERIC_STEP = re.compile(r"\b(work on (the|this) (task|first part|next part)|review (your )?progress|"
                          r"continue working|keep working)\b", re.I)

# What PIP acts out on the device while the step runs (names match firmware mascot_activity_name()).
Activity = Literal["general", "write", "computer", "read", "call", "clean", "exercise", "cook", "garden", "music",
                   "fix", "plan", "errand", "rest"]


class Step(BaseModel):
    title: str = Field(min_length=3, max_length=96)
    duration_min: int = Field(ge=1, le=60)
    is_starter: bool = False
    activity: Activity | None = None  # what the body does in this step (Kimi picks it; keyword rules otherwise)

    @model_validator(mode="after")
    def not_a_header(self) -> Step:
        if HEADER_LIKE.search(self.title) or (self.title.isupper() and len(self.title) > 4):
            raise ValueError(f"step '{self.title}' looks like a heading, not a concrete action")
        if GENERIC_STEP.search(self.title):
            raise ValueError(f"step '{self.title}' is generic filler - name the real action, object or place")
        return self


class ActiveTask(BaseModel):
    title: str = Field(min_length=2, max_length=64)
    short_title: str | None = Field(default=None, max_length=24)  # fits the 400x300 device header
    steps: list[Step]
    if_then_cue: str | None = None
    # when the user said they'll start ("in 10 minutes", "at 2"): local "YYYY-MM-DDTHH:MM"; PIP nudges then
    start_local: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")

    @model_validator(mode="after")
    def adhd_invariants(self) -> ActiveTask:
        """Structure is checked strictly; step lengths and the starter flag are repaired instead of rejecting a
        good plan (a 4-minute step once made PIP say "AI has left the device")."""
        if not 3 <= len(self.steps) <= 6:
            raise ValueError(f"active task needs 3-6 micro-steps, got {len(self.steps)}")
        first = self.steps[0]
        if ABSTRACT_STARTERS.match(first.title):
            raise ValueError(f"starter must be a concrete physical action, not '{first.title}'")
        first.is_starter = True
        first.duration_min = min(5, max(2, first.duration_min))
        for s in self.steps[1:]:
            s.is_starter = False
            s.duration_min = min(25, max(5, s.duration_min))
        return self


class ScheduledItem(BaseModel):
    kind: Literal["REMINDER", "ALARM", "TASK"]
    title: str = Field(min_length=2, max_length=64)
    when_text: str = ""
    due_local: str | None = None  # ISO local datetime "YYYY-MM-DDTHH:MM"
    needs_confirmation: bool = False
    repeat_days: str | None = Field(default=None, pattern=r"^(MO|TU|WE|TH|FR|SA|SU)(,(MO|TU|WE|TH|FR|SA|SU))*$")
    # ALARM only: spoken wake-up instead of chimes alone
    use_voice: bool = False
    voice_style: Literal["female", "male"] | None = None
    script: str | None = None  # ~30 s of speech (~70-90 words); a short/missing one is completed by the host

    @field_validator("script")
    @classmethod
    def tidy_script(cls, v: str | None) -> str | None:
        v = (v or "").strip().strip('"')
        return v[:1200] or None

    @property
    def needs_script(self) -> bool:
        return self.kind == "ALARM" and self.use_voice and len((self.script or "").split()) < 40


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


class ActionItem(BaseModel):
    task: str = Field(min_length=2, max_length=200)
    owner: str | None = Field(default=None, max_length=60)
    due: str | None = Field(default=None, max_length=60)
    said_at: str | None = Field(default=None, max_length=10)  # "mm:ss" where it was said (jump to the audio)
    done: bool = False    # ticked in the meeting's Obsidian note (or in PIP)
    parked: bool = False  # sent to PIP's parked tangents (kept for older summaries; see status)
    # filled by PIP, not by the model: the deadline as a date (meetings/due.py, user can edit), what the user made
    # of the item, and whether it is the user's own
    due_date: str | None = None   # YYYY-MM-DD
    due_time: str | None = None   # HH:MM when a time was said
    due_exact: bool = True        # False for soft deadlines ("next week")
    due_user: bool = False        # the user set the date: a re-summary keeps it
    status: str = "new"           # new | task | reminder | parked | dismissed
    ref_id: str | None = None     # the task / reminder / parked note made from it
    mine: bool = False            # owned by the user (Settings -> Meetings -> your name)


class MeetingSummary(BaseModel):
    """A meeting's summary - made on this PC by default (meetings/summarize.py) or by Kimi on request."""
    title: str = Field(min_length=2, max_length=80)
    summary: str = Field(min_length=2, max_length=2000)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)  # subjects discussed: Obsidian links + search
    key_points: list[str] = Field(default_factory=list)  # "[mm:ss] who - what", in meeting order
    outcome: str = Field(default="", max_length=600)  # how the meeting ended: what was concluded or agreed
