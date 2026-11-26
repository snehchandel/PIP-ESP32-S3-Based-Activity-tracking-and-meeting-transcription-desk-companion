"""Deadline words from a meeting ("Friday", "November 26th", "end of week", "by EOD tomorrow") -> a calendar date.

Deterministic, and relative to the MEETING's date, not today: "Friday" said in a Tuesday meeting is that week's
Friday even when the summary is made later. Small models are unreliable at date arithmetic, so the model only
copies the words that were said and this module works out the date. `exact` is False for soft deadlines ("next
week", "end of month") - the app shows those as "around" and lets the user fix the date."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time, timedelta

from ..calendar.timeparse import WEEKDAYS, _clock

MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"])}
MONTHS.update({m[:3]: n for m, n in list(MONTHS.items())})
MONTHS["sept"] = 9
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MD = re.compile(rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.I)          # November 26th
_DM = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})\b", re.I)   # 26th of November
_THE = re.compile(r"\b(?:the|on the|by the)\s+(\d{1,2})(?:st|nd|rd|th)\b", re.I)      # by the 26th
_IN = re.compile(r"\bin\s+(a|an|one|two|three|four|\d{1,2})\s+(day|days|week|weeks)\b", re.I)
_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4}


@dataclass(frozen=True)
class Due:
    day: date
    at: time | None = None   # a time of day when one was said ("by noon", "3pm")
    exact: bool = True       # False: "next week", "end of month"...


def _future(d: date, ref: date) -> date:
    """A month/day without a year: this year, or next year if it already passed well before the meeting."""
    return d if d >= ref - timedelta(days=7) else d.replace(year=d.year + 1)


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def resolve_due(text: str | None, meeting_day: date) -> Due | None:
    """None when the words carry no date at all ("soon", "when possible")."""
    if not text:
        return None
    low = " ".join(text.lower().split())
    at, _ = _clock(low)
    if at is None and re.search(r"\bnoon\b|\bmidday\b", low):
        at = time(12, 0)
    if at is None and re.search(r"\b(eod|end of (the )?day|close of business|cob)\b", low):
        at = time(17, 0)
    ref = meeting_day
    if m := _ISO.search(low):
        d = _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return Due(d, at) if d else None
    if m := _MD.search(low):
        d = _safe(ref.year, MONTHS[m.group(1).lower().rstrip(".")], int(m.group(2)))
        return Due(_future(d, ref), at) if d else None
    if m := _DM.search(low):
        d = _safe(ref.year, MONTHS[m.group(2).lower()], int(m.group(1)))
        return Due(_future(d, ref), at) if d else None
    if m := _THE.search(low):  # "by the 26th": this month, or next month if the day already passed
        n = int(m.group(1))
        d = _safe(ref.year, ref.month, n)
        if d is None or d < ref:
            nm = date(ref.year + (ref.month == 12), ref.month % 12 + 1, 1)
            d = _safe(nm.year, nm.month, n)
        return Due(d, at) if d else None
    if "day after tomorrow" in low:
        return Due(ref + timedelta(days=2), at)
    if re.search(r"\btomorrow\b", low):
        return Due(ref + timedelta(days=1), at)
    if re.search(r"\b(today|tonight|eod|end of (the )?day|close of business|cob)\b", low):
        return Due(ref, at or (time(17, 0) if "tonight" not in low else time(20, 0)))
    if m := _IN.search(low):
        n = _WORDS.get(m.group(1).lower()) or int(m.group(1))
        days = n * 7 if m.group(2).startswith("week") else n
        return Due(ref + timedelta(days=days), at, exact=m.group(2).startswith("day"))
    for i, wd in enumerate(WEEKDAYS):
        m = re.search(rf"\b(next\s+|this\s+)?{wd}\b", low)
        if m:
            delta = (i - ref.weekday()) % 7 or 7
            if m.group(1) and m.group(1).strip() == "next" and delta < 7 and ref.weekday() < i:
                delta += 7  # "next Friday" said on a Tuesday = Friday of next week
            return Due(ref + timedelta(days=delta), at)
    if re.search(r"\b(end of (the |this )?week|eow|by (the )?weekend|this week)\b", low):
        return Due(ref + timedelta(days=(4 - ref.weekday()) % 7), at, exact=False)  # that week's Friday
    if re.search(r"\bnext week\b", low):
        return Due(ref + timedelta(days=7 - ref.weekday()), at, exact=False)      # next Monday
    if re.search(r"\b(end of (the |this )?month|eom|this month)\b", low):
        nm = date(ref.year + (ref.month == 12), ref.month % 12 + 1, 1)
        return Due(nm - timedelta(days=1), at, exact=False)
    if re.search(r"\bnext month\b", low):
        return Due(date(ref.year + (ref.month == 12), ref.month % 12 + 1, 1), at, exact=False)
    if m := re.search(rf"\b(?:in|by|end of|early|mid|late)\s+({_MONTH})\b", low):  # "in February"
        mo = MONTHS[m.group(1).lower()]
        d = date(ref.year + (mo < ref.month), mo, 1)
        return Due(d, at, exact=False)
    return None
