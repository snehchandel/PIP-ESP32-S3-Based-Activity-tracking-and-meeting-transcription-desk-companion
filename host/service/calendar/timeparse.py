"""Deterministic natural-language time extraction with explicit ambiguity + DST handling."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
VAGUE_PARTS = {"morning": time(9, 0), "afternoon": time(14, 0), "evening": time(18, 0), "tonight": time(20, 0),
               "noonish": time(12, 0)}
VAGUE_WORDS = ("later", "sometime", "soon", "this week", "next week", "at some point", "whenever")

_TIME_REQ = re.compile(r"\b(?:at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?|(\d{1,2})(?::(\d{2}))\s*(am|pm)?|"
                       r"(\d{1,2})\s*(am|pm))\b", re.I)
_IN = re.compile(r"\bin\s+(\d{1,3})\s*(min|minute|minutes|hour|hours|hr|hrs)\b", re.I)


@dataclass
class ParsedTime:
    local: datetime | None        # aware datetime in the user's zone
    needs_confirmation: bool
    matched_text: str
    reason: str = ""


def resolve_local(d: date, t: time, tz: ZoneInfo) -> tuple[datetime, str]:
    """Build an aware local datetime. Nonexistent (spring-forward) -> shift to first valid instant;
    repeated (fall-back) -> fold=0 (first occurrence) and flag it."""
    naive = datetime.combine(d, t)
    aware = naive.replace(tzinfo=tz, fold=0)
    roundtrip = aware.astimezone(timezone.utc).astimezone(tz)
    if roundtrip.replace(tzinfo=None) != naive:
        probe = naive
        for _ in range(180):  # walk forward minute by minute to the first instant that exists
            probe += timedelta(minutes=1)
            cand = probe.replace(tzinfo=tz)
            if cand.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == probe:
                return cand, "nonexistent local time (DST gap) shifted forward"
        return roundtrip, "nonexistent local time (DST gap) shifted forward"
    other = naive.replace(tzinfo=tz, fold=1)
    if other.utcoffset() != aware.utcoffset():
        return aware, "ambiguous local time (DST overlap) - using first occurrence"
    return aware, ""


def _clock(text: str) -> tuple[time | None, str]:
    m = _TIME_REQ.search(text)
    if m:
        g = m.groups()
        hh, mm, ap = (g[0], g[1], g[2]) if g[0] else ((g[3], g[4], g[5]) if g[3] else (g[6], None, g[7]))
        h, mi = int(hh), int(mm or 0)
        if ap:
            ap = ap.lower().replace(".", "")
            if ap == "pm" and h < 12:
                h += 12
            if ap == "am" and h == 12:
                h = 0
        elif h <= 7:  # "at 3" with no am/pm: assume afternoon for a desk companion
            h += 12
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return time(h, mi), m.group(0)
    if re.search(r"\bnoon\b", text, re.I):
        return time(12, 0), "noon"
    if re.search(r"\bmidnight\b", text, re.I):
        return time(0, 0), "midnight"
    return None, ""


def _day(text: str, today: date) -> tuple[date | None, str]:
    low = text.lower()
    if "day after tomorrow" in low:
        return today + timedelta(days=2), "day after tomorrow"
    if re.search(r"\btomorrow\b", low):
        return today + timedelta(days=1), "tomorrow"
    if re.search(r"\btoday\b|\btonight\b", low):
        return today, "today"
    for i, wd in enumerate(WEEKDAYS):
        m = re.search(rf"\b(next\s+)?{wd}\b(?!'s|’s)", low)  # "Monday's demo" is a noun, not a date
        if m:
            delta = (i - today.weekday()) % 7 or 7
            if m.group(1):
                delta += 7 if delta < 7 else 0
            return today + timedelta(days=delta), m.group(0)
    return None, ""


def parse_when(text: str, now: datetime, tz: ZoneInfo) -> ParsedTime | None:
    """Return None when the text carries no time reference at all."""
    local_now = now.astimezone(tz)
    m = _IN.search(text)
    if m:
        n = int(m.group(1))
        delta = timedelta(hours=n) if m.group(2).lower().startswith("h") else timedelta(minutes=n)
        return ParsedTime(local_now + delta, False, m.group(0))
    day, day_txt = _day(text, local_now.date())
    clock, clock_txt = _clock(text)
    low = text.lower()
    vague_part = next((p for p in VAGUE_PARTS if re.search(rf"\b{p}\b", low)), None)
    vague_word = next((w for w in VAGUE_WORDS if w in low), None)
    if clock is None and vague_part is None and day is None:
        if vague_word:
            return ParsedTime(None, True, vague_word, "no concrete time")
        return None
    needs_conf = clock is None  # day-part or weekday only -> propose, but confirm
    t = clock or VAGUE_PARTS.get(vague_part or "", time(9, 0))
    d = day or local_now.date()
    if day is None and clock is not None and datetime.combine(d, t) <= local_now.replace(tzinfo=None):
        d = d + timedelta(days=1)  # "at 3pm" after 3pm means tomorrow
    when, dst_note = resolve_local(d, t, tz)
    matched = " ".join(x for x in (day_txt, clock_txt or (vague_part or "")) if x).strip()
    reason = "relative/vague time" if needs_conf else ""
    if dst_note:
        reason = f"{reason}; {dst_note}".strip("; ")
        needs_conf = needs_conf or "ambiguous" in dst_note
    return ParsedTime(when, needs_conf, matched, reason)


def strip_time_words(text: str) -> str:
    out = _IN.sub("", text)
    out = _TIME_REQ.sub("", out)
    out = re.sub(r"\b(next\s+)?(" + "|".join(WEEKDAYS) + r")\b", "", out, flags=re.I)
    out = re.sub(r"\b(tomorrow|today|tonight|noon|midnight|this|on|at|by|in the)\b", "", out, flags=re.I)
    out = re.sub(r"\b(" + "|".join(VAGUE_PARTS) + r")\b", "", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip(" ,.-")
