"""Planner behaviour across diverse brain dumps (LocalRule) + KimiPlanner retry/validation via mocked HTTP."""
from __future__ import annotations

import json

import httpx
import pytest
from service.planner import KimiPlanner, PlannerError, make_planner
from service.planner.local_rule import LocalRulePlanner
from service.planner.schema import IntentType

P = LocalRulePlanner("America/Toronto")

CASES = [  # text, intent, active-task substring, n_parked, scheduled kinds, needs_confirmation
    ("Finish Q3 report, also remind me to call dentist, and set alarm for 3pm", "CREATE_TASK", "q3 report", 1,
     ["ALARM"], False),
    ("I need to clean the kitchen. Oh and email Sarah later", "CREATE_TASK", "kitchen", 1, [], False),
    ("remind me to take meds at 9pm", "ADD_REMINDER", None, 0, ["REMINDER"], False),
    ("set an alarm for 7:30am tomorrow", "ADD_ALARM", None, 0, ["ALARM"], False),
    ("wake me up at 6", "ADD_ALARM", None, 0, ["ALARM"], False),
    ("remind me to call mom friday afternoon", "ADD_REMINDER", None, 0, ["REMINDER"], True),
    ("gym friday afternoon", "ADD_REMINDER", None, 0, ["TASK"], True),
    ("stuff", "NEEDS_CLARIFICATION", None, 0, [], False),
    ("everything", "NEEDS_CLARIFICATION", None, 0, [], False),
    ("pause", "CONTROL_COMMAND", None, 0, [], False),
    ("resume", "CONTROL_COMMAND", None, 0, [], False),
    ("I need a break", "CONTROL_COMMAND", None, 0, [], False),
    ("this step is too big", "CONTROL_COMMAND", None, 0, [], False),
    ("what's next", "QUERY_STATE", None, 0, [], False),
    ("plan my day", "MORNING_PLAN", None, 0, [], False),
    ("", "NO_ACTION", None, 0, [], False),
    ("Write the blog post about ADHD tools and also buy milk", "CREATE_TASK", "blog post", 1, [], False),
    ("study chapter 4 for the exam. by the way remind me to pay rent", "CREATE_TASK", "chapter 4", 1, [], False),
    ("fix the login bug, don't forget to water plants", "CREATE_TASK", "login bug", 1, [], False),
    ("do my taxes and also remind me to call the bank at 2pm", "CREATE_TASK", "taxes", 0, ["REMINDER"], False),
    ("um so I have to reply to emails", "CREATE_TASK", "emails", 0, [], False),
    ("Prepare slides for Monday's demo", "CREATE_TASK", "slides", 0, [], False),
    ("remind me later to stretch", None, None, 1, [], False),
    ("alarm sometime this afternoon", "ADD_ALARM", None, 0, ["ALARM"], True),
    ("clean my desk, then tidy the closet later", "CREATE_TASK", "desk", 1, [], False),
    ("set alarm in 20 minutes", "ADD_ALARM", None, 0, ["ALARM"], False),
]


@pytest.mark.parametrize("text,intent,active,n_parked,kinds,conf", CASES)
def test_local_rule_cases(text, intent, active, n_parked, kinds, conf, now) -> None:  # type: ignore[no-untyped-def]
    out = P.plan(text, now)
    if intent:
        assert out.intent.value == intent, out
    if active:
        assert out.active_task and active in out.active_task.title.lower()
    assert len(out.parked) == n_parked, [p.title for p in out.parked]
    assert [s.kind for s in out.scheduled] == kinds
    assert out.needs_confirmation is conf
    PlannerOutputV1 = type(out)
    PlannerOutputV1.model_validate_json(out.model_dump_json())  # every output re-validates


def test_case_count_meets_gate() -> None:
    assert len(CASES) >= 25


def test_factory_is_kimi_only() -> None:
    with pytest.raises(PlannerError):
        make_planner("", "u", "m", "America/Toronto")  # no silent offline fallback (ADR-013)
    assert make_planner("sk-test", "u", "m", "America/Toronto").mode == "KIMI"


def test_kimi_never_sends_temperature_and_unwraps_lists(now) -> None:  # type: ignore[no-untyped-def]
    seen: list[dict] = []  # type: ignore[type-arg]
    out = _kimi([_resp("```json\n" + json.dumps([VALID]) + "\n```")], seen).plan("x", now)
    assert out.intent == IntentType.CREATE_TASK
    assert "temperature" not in seen[0]  # kimi-k3 family only accepts the default


def test_header_like_steps_are_rejected() -> None:
    from pydantic import ValidationError
    from service.planner.schema import Step
    for bad in ("Preparation:", "Step 1: open the doc", "PACKING", "## Setup"):
        with pytest.raises(ValidationError):
            Step(title=bad, duration_min=5)


def test_resolve_model_prefers_newest_available() -> None:
    from service.planner.kimi import resolve_model

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "kimi-k2.6"}, {"id": "kimi-k3"}, {"id": "moonshot-v1"}]})
    c = httpx.Client(transport=httpx.MockTransport(handler))
    assert resolve_model(c, "https://x/v1", "k") == "kimi-k3"
    assert resolve_model(c, "https://x/v1", "k", preferred="kimi-k2.6") == "kimi-k2.6"
    assert resolve_model(c, "https://x/v1", "k", preferred="gone-model") == "kimi-k3"


VALID = {"intent": "CREATE_TASK", "active_task": {"title": "Q3 report", "steps": [
    {"title": "Open a blank doc", "duration_min": 2, "is_starter": True},
    {"title": "Write headings", "duration_min": 10}, {"title": "Draft section 1", "duration_min": 20}]},
    "parked": [{"title": "Call dentist", "source_text": "remind me to call dentist"}]}


def _kimi(responses: list[httpx.Response], seen: list[dict]) -> KimiPlanner:  # type: ignore[type-arg]
    it = iter(responses)

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return next(it)
    return KimiPlanner("sk-test", "https://api.moonshot.ai/v1", "kimi-k2-0905-preview",
                       client=httpx.Client(transport=httpx.MockTransport(handler)))


def _resp(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_kimi_valid_first_try(now) -> None:  # type: ignore[no-untyped-def]
    seen: list[dict] = []  # type: ignore[type-arg]
    out = _kimi([_resp(json.dumps(VALID))], seen).plan("x", now)
    assert out.intent == IntentType.CREATE_TASK and len(seen) == 1
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert seen[0]["model"] == "kimi-k2-0905-preview"


def test_kimi_retries_once_with_errors(now) -> None:  # type: ignore[no-untyped-def]
    bad = dict(VALID, active_task={"title": "Q3", "steps": [{"title": "Think about it", "duration_min": 2,
                                                             "is_starter": True}]})
    seen: list[dict] = []  # type: ignore[type-arg]
    out = _kimi([_resp(json.dumps(bad)), _resp(json.dumps(VALID))], seen).plan("x", now)
    assert out.active_task is not None and len(seen) == 2
    assert "failed validation" in seen[1]["messages"][-1]["content"]


def test_kimi_fails_after_second_invalid(now) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(PlannerError):
        _kimi([_resp("{not json"), _resp("{\"intent\": \"NOPE\"}")], []).plan("x", now)


def test_kimi_http_error_is_planner_error(now) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(PlannerError):
        _kimi([httpx.Response(401, json={"error": "bad key"})], []).plan("x", now)


def test_kimi_failure_shows_ai_left_and_keeps_the_thought(manager, now) -> None:  # type: ignore[no-untyped-def]
    from service.speech.pipeline import AiUnavailable, VoicePipeline

    kimi = _kimi([_resp("{}"), _resp("{}")], [])
    vp = VoicePipeline(manager, None, lambda: kimi, lambda k, p: None)  # type: ignore[arg-type]
    with pytest.raises(AiUnavailable):
        vp.process_text("Finish Q3 report", "k1", source="voice", auto_commit=True)
    assert manager.tasks.list_tasks() == []  # nothing half-committed
    assert manager.ui_state() == "ERROR_RECOVERABLE"
    assert manager.snapshot()["error_title"] == "AI has left the device"
    assert [p["title"] for p in manager.tasks.parked()] == ["Finish Q3 report"]  # words not lost
    assert manager.apply_button(1, 1) == "error_dismiss" and manager.ui_state() == "IDLE_READY"


def test_auto_model_never_picks_expensive_highspeed() -> None:
    import httpx
    from service.planner.kimi import resolve_model

    def models(ids: list[str]) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"id": i} for i in ids]})))

    assert resolve_model(models(["kimi-k3.1-pro-highspeed", "kimi-k3.1-pro"]), "http://x/v1", "k") == "kimi-k3.1-pro"
    assert resolve_model(models(["kimi-k9-turbo", "kimi-k9-highspeed", "kimi-k8"]), "http://x/v1", "k") == "kimi-k8"
