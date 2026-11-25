"""What kind of activity is a step? Decides what PIP acts out on the device while you do it.

Deterministic keyword rules (no AI call, works offline, costs nothing). Step titles are imperatives that lead with
their verb, so the *earliest* keyword in a title wins ("Create a task for going to bed" is planning, not sleep);
the step title wins over the task title. Names must match `mascot_activity_name()` in
firmware/components/mascot_renderer/mascot_acts.c."""
from __future__ import annotations

import re

ACTIVITIES = ("general", "write", "computer", "read", "call", "clean", "exercise", "cook", "garden", "music", "fix",
              "plan", "errand", "rest")

# on a tie (same position) the earlier rule wins
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("call", ("call", "phone", "ring", "dial", "facetime", "zoom", "meeting", "meet with", "voicemail", "text",
              "message", "chat with", "talk to", "speak to", "catch up with")),
    ("exercise", ("gym", "workout", "work out", "exercise", "run", "running", "jog", "jogging", "yoga", "stretch",
                  "pilates", "swim", "swimming", "bike", "biking", "cycle", "cycling", "lift", "push-up", "pushup",
                  "squat", "walk the dog", "hike", "hiking", "train", "training")),
    ("rest", ("bed", "bedtime", "sleep", "nap", "napping", "rest", "relax", "meditate", "breathe", "wind down",
              "lie down")),
    ("cook", ("cook", "bake", "dinner", "lunch", "breakfast", "meal", "recipe", "kitchen", "chop", "snack")),
    ("clean", ("clean", "tidy", "vacuum", "sweep", "mop", "mopping", "dust", "laundry", "dishes", "wash",
               "declutter", "fold", "trash", "garbage", "recycling", "iron", "scrub")),
    ("garden", ("water the plant", "water the flower", "plant", "garden", "weed", "lawn", "mow", "repot",
                "flower")),
    ("music", ("practice", "practise", "guitar", "piano", "sing", "song", "music", "violin", "drum", "playlist")),
    ("fix", ("fix", "repair", "assemble", "build", "install", "replace", "tighten", "mount", "set up", "setup",
             "screw", "drill")),
    ("errand", ("pick up", "drop off", "buy", "shop", "shopping", "groceries", "grocery", "store", "pharmacy",
                "post office", "errand", "drive", "collect", "return", "bank", "appointment", "book a", "book the",
                "reserve", "reservation")),
    ("computer", ("email", "e-mail", "inbox", "reply", "code", "coding", "program", "debug", "deploy",
                  "spreadsheet", "excel", "slides", "powerpoint", "website", "online", "upload", "download",
                  "invoice", "form", "login", "password", "account", "laptop", "computer", "app", "software",
                  "google", "search", "research", "file", "folder", "template", "tool")),
    ("read", ("read", "study", "studying", "review", "learn", "chapter", "article", "book", "course", "revise",
              "lecture", "textbook")),
    ("write", ("write", "writing", "draft", "journal", "essay", "report", "summary", "outline", "heading",
               "letter", "note", "list", "edit", "proofread", "blog", "post", "paragraph", "intro", "conclusion",
               "document", "doc")),
    ("plan", ("plan", "planning", "schedule", "calendar", "prioritize", "prioritise", "agenda", "goal", "budget",
              "decide", "brainstorm", "organize", "organise", "map out", "timeline", "task", "create a task")),
)

_ENDINGS = r"(?:s|es|ed|d|ing|er|ers|ies)?\b"
_COMPILED = tuple((name, re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")" + _ENDINGS, re.IGNORECASE))
                  for name, kws in _RULES)


def _classify_one(title: str) -> str | None:
    best: tuple[int, int, str] | None = None
    for order, (name, rx) in enumerate(_COMPILED):
        m = rx.search(title)
        if m and (best is None or (m.start(), order) < best[:2]):
            best = (m.start(), order, name)
    return best[2] if best else None


def classify(*titles: str | None) -> str:
    """First title with a match decides (pass the step title before the task title); "general" otherwise."""
    for title in titles:
        if title:
            found = _classify_one(title)
            if found:
                return found
    return "general"
