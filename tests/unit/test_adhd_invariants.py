"""The 7 ADHD behavioural invariants of spec section 2, verified end to end."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from service.planner.local_rule import LocalRulePlanner
from service.planner.schema import ActiveTask, IntentType, PlannerOutputV1, Step
from service.state.actions import split_calc

P = LocalRulePlanner("America/Toronto")


def test_1_one_active_lane_tangents_are_parked(now, manager) -> None:  # type: ignore[no-untyped-def]
    plan = P.plan("Write the grant proposal, also buy milk and oh and call Sam later", now)
    assert plan.active_task is not None and "grant proposal" in plan.active_task.title.lower()
    assert {p.title for p in plan.parked} >= {"Buy milk", "Call Sam"}
    for p in plan.parked:
        assert p.source_text  # original words preserved
    out = manager.commit_plan(plan, "x")
    active = [t for t in manager.tasks.list_tasks() if t["status"] == "ACTIVE"]
    assert len(active) == 1 and active[0]["id"] == out["task_id"]
    # a second plan never steals the lane while a step is active
    manager.commit_plan(P.plan("Clean the garage", now), "y")
    assert len([t for t in manager.tasks.list_tasks() if t["status"] == "ACTIVE"]) == 1


@pytest.mark.parametrize("text", ["Finish Q3 report", "clean the kitchen", "study chapter 4", "fix the login bug",
                                  "reply to emails", "do my taxes", "repaint the fence"])
def test_2_starter_is_physical_2_to_5_minutes(text: str, now) -> None:  # type: ignore[no-untyped-def]
    t = P.plan(text, now).active_task
    assert t is not None
    s0 = t.steps[0]
    assert s0.is_starter and 2 <= s0.duration_min <= 5
    assert not s0.title.lower().startswith(("think", "plan", "consider", "reflect"))


def test_2_abstract_starter_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ActiveTask(title="Report", steps=[Step(title="Think about the report", duration_min=2, is_starter=True),
                                          Step(title="Write", duration_min=10), Step(title="Edit", duration_min=10)])


@pytest.mark.parametrize("text", ["Finish Q3 report", "clean the kitchen", "repaint the fence"])
def test_3_three_to_six_steps_with_bounded_durations(text: str, now) -> None:  # type: ignore[no-untyped-def]
    t = P.plan(text, now).active_task
    assert t is not None and 3 <= len(t.steps) <= 6
    assert all(5 <= s.duration_min <= 25 for s in t.steps[1:])


def test_3_vague_input_asks_for_clarification(now) -> None:  # type: ignore[no-untyped-def]
    plan = P.plan("stuff", now)
    assert plan.intent == IntentType.NEEDS_CLARIFICATION and plan.clarification_question
    assert plan.active_task is None


def test_3_schema_rejects_too_few_steps() -> None:
    with pytest.raises(ValidationError):
        ActiveTask(title="X task", steps=[Step(title="Open doc", duration_min=2, is_starter=True),
                                          Step(title="Write it", duration_min=10)])


@pytest.mark.parametrize("remaining", [120, 121, 150, 240, 599, 600, 1500, 3599])
def test_4_cut_in_half_never_loses_work(remaining: int) -> None:
    cur, nxt = split_calc(remaining)
    assert cur == max(120, remaining // 2)
    assert nxt >= 120 and cur + nxt >= remaining


def test_4_split_keeps_original_steps(now, manager) -> None:  # type: ignore[no-untyped-def]
    manager.commit_plan(P.plan("Finish Q3 report", now), "x")
    before = manager.active_task()["steps"]
    manager.timer.load(1500_000, 1500_000, "PAUSED")
    cur, nxt = manager.rescue_split()
    after = manager.active_task()["steps"]
    assert len(after) == len(before) + 1
    assert all(s["status"] != "COMPLETED" for s in after)  # nothing falsely completed
    assert manager.timer.remaining_ms == cur * 1000


def test_5_pause_preserves_exact_remaining(manager, now) -> None:  # type: ignore[no-untyped-def]
    manager.commit_plan(P.plan("Finish Q3 report", now), "x")
    manager.timer_start()
    manager._clock["t"] += 37.25
    manager.timer_pause()
    rem = manager.timer.remaining_ms
    assert rem == 120_000 - 37_250
    manager._clock["t"] += 600
    manager.page = "AGENDA"
    assert manager.timer.remaining_ms == rem
    assert manager.snapshot()["remaining_ms"] == rem


def test_5_no_shame_copy(manager, now) -> None:  # type: ignore[no-untyped-def]
    manager.commit_plan(P.plan("Finish Q3 report", now), "x")
    manager.complete_step()
    snap = manager.snapshot()
    assert snap["ui_state"] == "STEP_DONE"
    text = " ".join(str(v) for v in snap.values()).lower()
    for bad in ("overdue", "late", "failed", "streak", "behind"):
        assert bad not in text


def test_6_ambiguous_times_need_confirmation_and_are_not_armed(manager, now) -> None:  # type: ignore[no-untyped-def]
    plan = P.plan("remind me to call mom friday afternoon", now)
    assert plan.needs_confirmation
    manager.commit_plan(plan, "x")
    assert manager.tasks.reminders() == [] and manager.alarms.list() == []
    assert manager.ui_state() == "NEEDS_CONFIRMATION"
    assert "Friday at 2:00 PM" in manager.snapshot()["clarification_text"]
    manager.confirm_pending()
    assert len(manager.tasks.reminders()) == 1


def test_7_intent_enum_is_exact() -> None:
    assert {i.value for i in IntentType} == {"CREATE_TASK", "MORNING_PLAN", "CONTROL_COMMAND", "ADD_REMINDER",
                                            "ADD_ALARM", "RESCHEDULE_ITEM", "QUERY_STATE", "NO_ACTION",
                                            "NEEDS_CLARIFICATION"}
    with pytest.raises(ValidationError):
        PlannerOutputV1.model_validate({"intent": "DO_MAGIC"})
