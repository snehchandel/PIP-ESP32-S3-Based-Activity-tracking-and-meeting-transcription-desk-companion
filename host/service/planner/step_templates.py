"""Concrete micro-step templates for the offline LocalRulePlanner.

Every template starts with a 2-minute *physical* starter and keeps follow-up steps 5-25 minutes."""
from __future__ import annotations

import re

Template = list[tuple[str, int]]

CATEGORIES: list[tuple[re.Pattern[str], Template]] = [
    (re.compile(r"\b(report|write|draft|essay|doc|document|proposal|summary|article|blog|paper|slides?|deck|"
                r"presentation|memo|letter|post)\b", re.I), [
        ("Open a blank doc for {obj} and type its title", 2),
        ("Write 3 headings for {obj}", 8),
        ("Draft the first section of {obj}", 20),
        ("Fill in the remaining sections", 25),
        ("Read it through once and save", 10),
    ]),
    (re.compile(r"\b(email|emails|inbox|reply|message|messages|slack)\b", re.I), [
        ("Open your inbox and star the 3 most urgent", 2),
        ("Reply to the first starred message", 10),
        ("Reply to the other two", 15),
        ("Archive or snooze everything else you can", 10),
    ]),
    (re.compile(r"\b(clean|tidy|declutter|laundry|dishes|vacuum|organize|organise)\b", re.I), [
        ("Stand up and put 5 things near you where they belong", 2),
        ("Clear one surface in {obj} completely", 10),
        ("Clean the main area of {obj}", 20),
        ("Take out trash and put supplies away", 5),
    ]),
    (re.compile(r"\b(study|read|learn|review|revise|homework|course|chapter|notes)\b", re.I), [
        ("Open your notes or book to the right page", 2),
        ("Skim headings and write 3 questions", 8),
        ("Work through the first section of {obj}", 20),
        ("Answer your 3 questions from memory", 10),
    ]),
    (re.compile(r"\b(code|coding|bug|fix|implement|feature|deploy|refactor|test|tests|pr)\b", re.I), [
        ("Open the project and run the tests once", 2),
        ("Write down the smallest change to {obj}", 5),
        ("Make that change", 20),
        ("Run tests and commit", 10),
    ]),
    (re.compile(r"\b(budget|taxes|tax|invoice|invoices|bills|expenses|spreadsheet)\b", re.I), [
        ("Open the spreadsheet or folder for {obj}", 2),
        ("Gather the documents you need into one place", 10),
        ("Enter the first batch of numbers", 20),
        ("Check totals and save a copy", 10),
    ]),
]

GENERIC: Template = [
    ("Put the tools or files for {obj} in front of you", 2),
    ("Write down the very first concrete action for {obj}", 5),
    ("Do the first part of {obj}", 20),
    ("Note where you stopped and the next step", 5),
]


LEAD_VERB = re.compile(r"^(?:finish|finally|write|draft|do|complete|work on|start|make|prepare|create|clean|tidy|"
                       r"organi[sz]e|study|read|review|revise|learn|fix|implement|code|send|answer|reply to|"
                       r"go through|sort|file|pay|update|build|plan|edit)\s+(?:up\s+)?", re.I)


def object_phrase(task_title: str) -> str:
    """'Finish Q3 report' -> 'Q3 report'; 'clean the kitchen' -> 'the kitchen'."""
    obj = task_title.strip().rstrip(".")
    prev = None
    while prev != obj:
        prev = obj
        obj = LEAD_VERB.sub("", obj)
    obj = obj or task_title.strip()
    return obj if obj[:2].isupper() or obj[:1].isdigit() else obj[:1].lower() + obj[1:]


def steps_for(task_title: str) -> list[dict[str, object]]:
    template = GENERIC
    for pattern, tpl in CATEGORIES:
        if pattern.search(task_title):
            template = tpl
            break
    obj_l = object_phrase(task_title)
    out = []
    for i, (title, minutes) in enumerate(template):
        text = title.format(obj=obj_l)
        if len(text) > 96:
            text = text[:93].rsplit(" ", 1)[0] + "..."
        out.append({"title": text[0].upper() + text[1:], "duration_min": minutes, "is_starter": i == 0})
    return out
