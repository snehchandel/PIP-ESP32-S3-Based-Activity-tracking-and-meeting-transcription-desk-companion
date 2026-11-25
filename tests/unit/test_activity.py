"""Step titles -> what PIP acts out on the device (firmware mascot_activity_from_name)."""
from __future__ import annotations

import pytest
from service.planner.activity import ACTIVITIES, classify


@pytest.mark.parametrize(("title", "expected"), [
    ("Draft the summary section for Q3", "write"),
    ("Call dentist", "call"),
    ("Text Sam about Friday", "call"),
    ("Pick up your son", "errand"),
    ("Book a restaurant", "errand"),
    ("Go to the gym", "exercise"),
    ("Stretch for 5 minutes", "exercise"),
    ("Water the plants", "garden"),
    ("Plant tomatoes", "garden"),
    ("Vacuum the living room", "clean"),
    ("Fold the laundry", "clean"),
    ("Read chapter 3", "read"),
    ("Reply to emails", "computer"),
    ("Cook dinner", "cook"),
    ("Fix the bike", "fix"),
    ("Plan next week", "plan"),
    ("Create a task for going to bed", "plan"),  # the earliest keyword wins, not "bed"
    ("Practice guitar", "music"),
    ("Take a nap", "rest"),
    ("Do the thing", "general"),
])
def test_classify(title: str, expected: str) -> None:
    assert classify(title) == expected


def test_word_boundaries_and_fallbacks() -> None:
    assert classify("Try the new restaurant") != "rest"  # "rest" must not match "restaurant"
    assert classify("Update the planet poster") != "plan"
    assert classify("", "Write the Q3 report") == "write"  # the task title is the fallback
    assert classify("Phone the bank", "Write the Q3 report") == "call"  # the step wins
    assert classify(None) == "general"
    assert set(ACTIVITIES) >= {classify(t) for t in ("Cook", "Read", "Nap", "Mow the lawn", "Install the shelf")}


def test_snapshot_carries_activities(manager) -> None:  # type: ignore[no-untyped-def]
    snap = manager.snapshot()
    assert {"activity", "next_activity", "done_activity"} <= snap.keys()
    assert all(snap[k] in ACTIVITIES for k in ("activity", "next_activity", "done_activity"))
