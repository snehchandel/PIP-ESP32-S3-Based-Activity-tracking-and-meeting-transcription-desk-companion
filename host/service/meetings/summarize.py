"""Meeting summaries on this PC.

Quality target: as good as Kimi's. What that took (ADR-031, tuned on real meetings):
- One pass whenever the transcript fits: up to ~11k tokens (about an hour of talk) is read whole, so nothing is
  lost between parts. This needs a 16k context, which fits an 8B model fully on an 8 GB GPU with Ollama's
  flash attention + q8_0 cache (OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0). The context is sized to
  each prompt, so short meetings stay fast.
- Longer meetings: ~6k-token parts (~30 min) at speaker turns, each returning rich notes (up to 10 dated key
  points, decisions, action items), then one merge call. Parts make the job pausable: between parts the worker
  steps aside for a new transcription or a voice command and keeps the notes already made.
- A prompt that fills the fields in a deliberate order - key points across the whole meeting first, then
  topics, decisions, action items, and the summary last - so the summary is written from an outline of the
  whole meeting, not from its first minutes. Clear definitions (a decision is agreed, an action item is someone's
  next step) with an example, because small models otherwise copy every action into decisions.
- "Careful" mode (the default) lets the model think before the final answer (Qwen 3 thinking), which is what
  closes most of the remaining gap to Kimi; "fast" skips it.
- Filler words ("um", "uh", stutters) are removed before sending (~5-10 % fewer tokens, less noise).
- Code, not the model, cleans up: empty placeholders ("not specified", "TBD"), owners matched to speaker
  names, decisions that only repeat an action item, duplicates."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol

from ..planner.schema import MeetingSummary
from ..speech.cleanup import clean_text
from .export import clock, speaker_turns

CHARS_PER_TOKEN = 4.2       # English transcript text with "[mm:ss] Name:" prefixes (qwen3 measured ~4.4)
CTX_MAX = 16384             # fits fully on an 8 GB GPU with the q8_0 cache
THINK_BUDGET = 2000         # extra tokens for thinking (careful mode; measured 300-800 on real meetings)
ANSWER_BUDGET = 2500        # tokens for the JSON answer (10+ key points, actions, summary: ~1.2-1.7k measured)
SINGLE_PASS_TOKENS = CTX_MAX - THINK_BUDGET - ANSWER_BUDGET - 900  # ~10k tokens of transcript: ~1 hour
CHUNK_TOKENS = 6000         # longer meetings: ~30-minute parts
SYSTEM_TOKENS = 900         # the prompt itself


class JsonLLM(Protocol):
    def chat_json(self, system: str, user: str, schema: dict[str, Any], purpose: str,
                  max_out: int = 1200, num_ctx: int = 8192, think: bool = False) -> dict[str, Any]: ...


class Yielded(Exception):  # noqa: N818 - control flow, not an error
    """Raised between two parts when more urgent work is waiting; the notes made so far are kept."""


_STR = {"type": "string"}
_ACTIONS = {"type": "array", "items": {"type": "object", "properties": {
    "said_at": _STR, "task": _STR, "owner": {"type": ["string", "null"]}, "due": {"type": ["string", "null"]}},
    "required": ["said_at", "task", "owner", "due"]}}
_LIST = {"type": "array", "items": _STR}
_DECISIONS = {"type": "array", "items": {"type": "object", "properties": {"said_at": _STR, "decision": _STR},
                                         "required": ["said_at", "decision"]}}
# Field order = the order the model writes them: outline first, the summary last (written from the outline).
SUMMARY_SCHEMA = {"type": "object", "properties": {"key_points": _LIST, "topics": _LIST, "decisions": _DECISIONS,
                                                   "action_items": _ACTIONS, "outcome": _STR, "summary": _STR,
                                                   "title": _STR},
                  "required": ["key_points", "topics", "decisions", "action_items", "outcome", "summary", "title"]}
NOTES_SCHEMA = {"type": "object", "properties": {"key_points": _LIST, "decisions": _DECISIONS, "action_items": _ACTIONS,
                                                 "topics": _LIST},
                "required": ["key_points", "decisions", "action_items", "topics"]}

DEFINITIONS = """Definitions (follow them strictly):
- DECISION ("said_at" = the [mm:ss] where it was agreed): something the speakers agreed, concluded or ruled
  out - including conclusions such as "this vendor isn't the right choice" or "we'll keep the current form" or
  "push it to next quarter". A decision is NOT a task;
  never copy an action item into decisions. Never list non-decisions ("no decision was made") or descriptions of
  how something works.
- ACTION ITEM: a concrete next step someone committed to or was asked to do. Scan the WHOLE transcript for
  commitments and requests: "I'll ...", "I will ...", "let me ...", "can you ...", "please ...", "we need to ...",
  "next step", "follow up", "send", "share", "check", "book", "talk to". "said_at" = the [mm:ss] of the line where
  it was said. "task" starts with a verb and names the object and the person involved (not just "Follow up").
  "owner" = who will do it: "I'll send it" -> the speaker of that line; "<name>, can you check?" -> that name;
  null if nobody took it on. "due" = the deadline words exactly as said (a weekday, a date, "end of week",
  "by noon tomorrow"), else null. General advice or wishes ("try harder", "learn more about it") are not action
  items unless someone committed to a concrete step.
- TOPICS: 3-7 short noun phrases (2-5 words) naming the main subjects of the WHOLE meeting - not people.
Only use what is in THIS transcript. The transcript comes from speech recognition: words may be mis-heard. Use the
listed spellings of names and terms, read past obvious mis-hearings, and never invent facts, names or dates.
No markdown, no emojis."""

ANALYST = """You are an expert meeting analyst writing the notes {who} would want after this meeting.
The transcript is split into timed sections ("### Section k (start-end)"); lines are "[mm:ss] Speaker: words".
The task to do is given after the transcript.
""" + DEFINITIONS

MAIN_TASK = """TASK - fill the JSON fields IN THIS ORDER:
1. key_points: for EACH section, 1-2 short sentences, and 2-3 for the last section (so the points cover the whole
   meeting, start to end), each starting with its [mm:ss], saying who said or concluded what, with specifics
   (systems, numbers, dates, names).
2. topics. 3. decisions. 4. action_items (see the definitions; check every section).
5. outcome: 1-2 sentences on how the meeting ended - what the speakers concluded or agreed by the end. Read the
   last section closely: conclusions are often said politely or indirectly ("so it sounds like we'll hold off
   for now", "let's leave it there", "I'll get back to you").
6. summary: 4-7 plain sentences written from your key points: why they met, the main threads with who said what,
   and the outcome.
7. title: what the meeting was about, at most 60 characters."""

SCAN_TASK = """TASK - list every decision and every action item in the transcript (see the definitions). Go section by
section and look for the cue words ("I'll", "let me", "can you", "we need to", "next step", "send", "share",
"check", "talk to", "agreed", "let's", "hold off"). List only items where such words were actually said - not
things that were merely discussed, explained or wished for. Write each action item as a task starting with a
verb ("Send ...", "Check ...") - never copy the spoken sentence ("I'll submit a few" -> task "Submit a few test
leads and share screenshots", owner = that speaker). Give each its said_at [mm:ss]."""

WRITER_PROMPT = """You write the final summary of a meeting for {who}, from checked notes and the end of the
transcript (lines are "[mm:ss] Speaker: words"). Fill IN THIS ORDER:
1. outcome: 1-2 sentences on how the meeting ended - what the speakers concluded or agreed by the end. Conclusions
   are often said politely or indirectly ("so it sounds like we'll hold off for now") - state them plainly.
2. summary: 4-7 plain sentences: why they met, the main threads with who said what (use the key points), the
   decisions and next steps, and the outcome. Specific, factual, no filler, nothing that is not in the notes.
3. title: what the meeting was about, at most 60 characters.
Use the speaker names as written. No markdown, no emojis."""
WRITER_SCHEMA = {"type": "object", "properties": {"outcome": _STR, "summary": _STR, "title": _STR},
                 "required": ["outcome", "summary", "title"]}
SCAN_SCHEMA = {"type": "object", "properties": {"decisions": _DECISIONS, "action_items": _ACTIONS},
               "required": ["decisions", "action_items"]}

PART_PROMPT = """You take notes on part {i} of {n} of a long meeting transcript (lines are "[mm:ss] Speaker:
words"). Another step will merge the notes of all parts, so be complete and specific:
- key_points: up to 10 short sentences spread over the whole part, each starting with its [mm:ss], saying who said
  or concluded what, with specifics (systems, numbers, dates, names);
- decisions, action_items, topics for THIS part only (see definitions); empty lists when there are none.
""" + DEFINITIONS

MERGE_PROMPT = """You get the notes of every part of one meeting, in order, and write the final notes {who} would
want. Fill the JSON fields IN THIS ORDER:
1. key_points: 8-14 points across ALL parts (some from every part), in order, each keeping its [mm:ss].
2. topics: 3-7 for the whole meeting. 3. decisions. 4. action_items: keep every distinct one; merge duplicates; a
   later part overrides an earlier one when they disagree (a changed decision, a moved deadline); keep "said_at"
   and the deadline words as said.
5. outcome: 1-2 sentences on how the meeting ended - what the speakers concluded or agreed by the end (the last
   part's notes), including conclusions said politely or indirectly.
6. summary: 4-7 plain sentences: why they met, the main threads with who said what, and the outcome.
7. title: what the meeting was about, at most 60 characters.
""" + DEFINITIONS

VERIFY_PROMPT = """You check candidate notes from a meeting against the transcript excerpt where each was said
(lines are "[mm:ss] Speaker: words"). For every candidate decide, using only its excerpt:
- keep: true only if the excerpt really shows it. When in doubt, keep=false.
  A DECISION must be something the speakers agreed, concluded or ruled out ("let's go with X", "so we won't do
  Y", "agreed", "we'll hold off"). keep=false for facts, descriptions, opinions, interests, advice and
  anything reported with "states / confirms / explains / notes / says / acknowledges / is interested".
  An ACTION ITEM must be a concrete next step someone committed to ("I'll ...", "let me ...") or was asked to do
  and accepted ("can you ...?" "sure"). keep=false for advice, wishes, questions, "consider ...", "explore ...",
  general goals, something already done, or a restatement of what was discussed in the meeting itself.
- For kept action items fix "owner" = the person who will DO it: "I'll do X" -> the speaker of that line. Advice
  from A to B ("you should talk to Jordan") is B's step only if it is clearly theirs to do - never A's. Fix "text"
  to say exactly what (verb + object + any person involved). "due" = the deadline words as said, or null.
- For kept decisions, "text" states the decision in one plain sentence; owner and due are null.
Return every candidate once, with its id. No markdown."""
VERIFY_SCHEMA = {"type": "object", "properties": {"checks": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "integer"}, "keep": {"type": "boolean"}, "text": _STR, "owner": {"type": ["string", "null"]},
    "due": {"type": ["string", "null"]}}, "required": ["id", "keep", "text", "owner", "due"]}}},
    "required": ["checks"]}
EXCERPT_BEFORE_S, EXCERPT_AFTER_S = 75, 45

_EMPTY = {"", "null", "none", "n/a", "na", "not specified", "unspecified", "unknown", "tbd", "tba", "unclear",
          "not mentioned", "not stated", "not given", "no deadline", "-", "--", "?", "none specified", "not set"}
_NON_DECISION = re.compile(r"\bno (?:formal |final |clear |firm )?decision\b|\bnot (?:yet )?decided\b|"
                           r"\bremains? (?:unclear|open|undecided)\b|\bwas not (?:agreed|decided)\b", re.I)
_REPORTED = re.compile(r"^\s*[A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*)?\s+(?:states?|stated|confirms?|confirmed|explains?|"
                       r"explained|notes?|noted|says?|said|mentions?|mentioned|acknowledges?|acknowledged|"
                       r"is interested|expressed|describes?|described|clarifies|clarified)\b", re.I)
# "action items" that are statements ("The printer issue does not affect...") or advice/goals ("Alex should become a
# manager", "Consider other options") - seen from qwen3:8b even after the check pass
_NOT_A_TASK = re.compile(r"^(?:the|a|an|there|it|this|that|these|those)\b|"
                         r"^(?:[A-Z][\w'-]*\s+)?(?:should|could|might|may)\s+(?:consider|explore|become|try|think|"
                         r"keep|continue|be)\b|^(?:consider|explore|think about|keep in mind)\b|"
                         # a quoted line of talk rather than a task ("We can sign off...", "Are not in scope...")
                         r"^(?:we|we're|we'll|i|i'm|i'll|you|you're|they|he|she|are|is|was|were|so|yeah|yes|okay|ok|"
                         r"well|and|but|if|maybe|other than|other|also|just|um|oh|no)\b|\?\s*$", re.I)
_NARRATED = re.compile(r"^([A-Z][\w'-]+(?: [A-Z][\w'-]+)?) (?:will|to|should|needs to|is going to|is to|has to|"
                       r"agreed to|offered to|committed to|confirmed (?:he|she|they) will) (.+)$")
_EVERYONE = {"team", "everyone", "all", "the team", "everybody", "all of us", "group", "the group"}


def est_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def tidy(text: str) -> str:
    """Drop fillers ("um", "uh") and stutters ("we we we") - the words carry nothing for a summary. Same clean-up as
    the transcript itself (speech/cleanup.py); a no-op on lines that were already cleaned."""
    return clean_text(text)


def transcript_lines(meeting: dict[str, Any], segments: list[dict[str, Any]]) -> list[str]:
    """Compact "[mm:ss] Name: text" lines, one per speaker turn - the cheapest form that still says who and when."""
    names = {sp["key"]: sp["name"] for sp in meeting.get("speakers", [])}
    out = []
    for name, t, text in speaker_turns(segments, names):
        text = tidy(text)
        if text:
            out.append(f"[{clock(t)}] {name}: {text}")
    return out


def sectioned(lines: list[str], minutes: float) -> str:
    """The transcript with "### Section k (start-end)" markers about every 5-6 minutes (3-10 sections, by text
    length), so the model is asked for points from every stretch of the meeting, not just its first minutes."""
    n = max(3, min(10, round(minutes / 5.5)))
    total = sum(len(x) for x in lines) or 1
    out: list[str] = []
    cur: list[str] = []
    size = 0
    for line in lines:
        cur.append(line)
        size += len(line)
        if size >= total * (len(out) + 1) / n and len(out) < n - 1:
            out.append("\n".join(cur))
            cur = []
    if cur:
        out.append("\n".join(cur))
    marked = []
    for k, block in enumerate(out, 1):
        stamps = re.findall(r"^\[([\d:]+)\]", block, re.M)
        span = f" ({stamps[0]}-{stamps[-1]})" if stamps else ""
        marked.append(f"### Section {k}{span}\n{block}")
    return "\n\n".join(marked)


def chunks(lines: list[str], size_chars: int) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    n = 0
    for line in lines:
        if cur and n + len(line) > size_chars:
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(line[: size_chars])  # one monologue longer than a part is cut, not dropped
        n += len(cur[-1]) + 1
    if cur:
        out.append("\n".join(cur))
    return out


def _s(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n].strip(" .;,") if v is not None else ""


def _empty(v: Any) -> bool:
    return _s(v, 80).lower().strip(" .") in _EMPTY


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def _similar(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def clean(data: dict[str, Any], fallback_title: str, speakers: list[str] | None = None) -> dict[str, Any]:
    """Whatever the model returned -> a valid MeetingSummary dict (trimmed, de-duplicated, no placeholders)."""
    speakers = speakers or []
    by_lower = {n.lower(): n for n in speakers}

    def uniq(items: list[Any], n: int, limit: int) -> list[str]:
        seen: dict[str, str] = {}
        for it in items:
            s = _s(it, n)
            if len(s) >= 2 and not _empty(s) and s.lower() not in seen:
                seen[s.lower()] = s
        return list(seen.values())[:limit]

    def owner(v: Any) -> str | None:
        if _empty(v):
            return None
        o = _s(v, 60)
        if o.lower() in _EVERYONE:
            return "Everyone"
        return by_lower.get(o.lower(), o)

    actions, seen = [], set()
    for a in data.get("action_items") or []:
        if not isinstance(a, dict):
            continue
        task = _s(a.get("task"), 200)
        # "Priya will double-check X" / "Jordan to send X" -> "Double-check X" (the owner says who)
        m_who = _NARRATED.match(task)
        if m_who and (not a.get("owner") or m_who.group(1).lower() in str(a.get("owner")).lower()):
            a = {**a, "owner": a.get("owner") or m_who.group(1)}
            task = m_who.group(2)
        if len(task) < 3 or _empty(task) or _NOT_A_TASK.search(task) or any(
                task.lower() == x.lower() or _similar(task, x) for x in seen):
            continue
        seen.add(task)
        at = re.search(r"\d{1,2}:\d{2}(?::\d{2})?", str(a.get("said_at") or ""))
        actions.append({"task": task[0].upper() + task[1:], "owner": owner(a.get("owner")),
                        "due": None if _empty(a.get("due")) else _s(a.get("due"), 60),
                        "said_at": at.group(0) if at else None})
    raw_dec = [d.get("decision") if isinstance(d, dict) else d for d in data.get("decisions") or []]
    decisions = [d for d in uniq(raw_dec, 300, 15)
                 if not any(_similar(d, a["task"]) for a in actions)  # a decision that only repeats a task
                 and not _NON_DECISION.search(d) and not _REPORTED.search(d)]
    topics = uniq([_cut(str(t).strip("#[] "), 60) for t in data.get("topics") or []], 60, 7)
    title = _s(data.get("title"), 80)
    summary = " ".join(str(data.get("summary") or "").split())[:2000]
    out = {"title": title if len(title) >= 2 else fallback_title[:80] or "Meeting",
           "summary": summary if len(summary) >= 2 else "No summary could be made from this transcript.",
           "decisions": decisions, "action_items": actions[:30], "topics": topics,
           "key_points": uniq(data.get("key_points") or [], 300, 16),
           "outcome": " ".join(str(data.get("outcome") or "").split())[:600]}
    return MeetingSummary.model_validate(out).model_dump()


def _cut(s: str, n: int) -> str:
    """At most n characters, cut at a word boundary."""
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0]


def _notes_text(i: int, n: int, part: str, notes: dict[str, Any]) -> str:
    first = re.match(r"\[([\d:]+)\]", part)
    last = re.findall(r"^\[([\d:]+)\]", part, re.M)
    span = f" ({first.group(1)}-{last[-1]})" if first and last else ""
    lines = [f"Part {i}/{n}{span}:"]
    lines += [f"- {_s(p, 300)}" for p in notes.get("key_points") or notes.get("points") or []]
    for d in notes.get("decisions") or []:
        text, at = (d.get("decision"), d.get("said_at")) if isinstance(d, dict) else (d, None)
        if not _empty(text):
            lines.append(f"Decision: {'[' + _s(at, 10).strip('[]') + '] ' if not _empty(at) else ''}{_s(text, 250)}")
    for a in notes.get("action_items") or []:
        if isinstance(a, dict) and a.get("task"):
            extra = "; ".join(f"{k} {_s(a.get(k), 60)}" for k in ("owner", "due") if not _empty(a.get(k)))
            at = f"[{_s(a.get('said_at'), 10).strip('[]')}] " if not _empty(a.get("said_at")) else ""
            lines.append(f"Action: {at}{_s(a['task'], 200)}" + (f" ({extra})" if extra else ""))
    if notes.get("topics"):
        lines.append("Topics: " + ", ".join(_s(t, 40) for t in notes["topics"]))
    return "\n".join(lines)


def _secs(stamp: Any) -> float | None:
    m = re.search(r"(?:(\d+):)?(\d{1,2}):(\d{2})", str(stamp or ""))
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


VERIFY_BATCH = 8           # candidates per check call (a long answer gets cut off and loses checks)
MAX_ACTIONS, MAX_DECISIONS = 12, 8   # an ADHD-friendly list: the main pass's items first, then the scan's


def verify(llm: JsonLLM, lines: list[str], data: dict[str, Any]) -> dict[str, Any]:
    """Second look (careful mode): every decision and action item is checked against the minute of transcript
    where it was said - drops facts/advice listed as decisions or tasks and fixes owners. Items the main pass
    found survive a failed or missing check; items only the scan found (marked "_scan") must be confirmed."""
    timed = [(_secs(m.group(1)) if (m := re.match(r"\[([\d:]+)\]", ln)) else None, ln) for ln in lines]
    cands: list[tuple[str, dict[str, Any]]] = []
    for d in data.get("decisions") or []:
        if isinstance(d, dict) and _secs(d.get("said_at")) is not None and not _empty(d.get("decision")):
            cands.append(("decision", d))
    for a in data.get("action_items") or []:
        if isinstance(a, dict) and _secs(a.get("said_at")) is not None and not _empty(a.get("task")):
            cands.append(("action", a))
    checks: dict[int, dict[str, Any]] = {}
    for start in range(0, len(cands), VERIFY_BATCH):
        blocks = []
        for i in range(start, min(len(cands), start + VERIFY_BATCH)):
            kind, c = cands[i]
            t = _secs(c.get("said_at")) or 0.0
            ex = "\n".join(ln for ts, ln in timed if ts is not None and t - EXCERPT_BEFORE_S <= ts <= t + EXCERPT_AFTER_S)
            what = c.get("decision") if kind == "decision" else (
                f"{c.get('task')} | owner: {c.get('owner')} | due: {c.get('due')}")
            blocks.append(f"Candidate {i} ({kind}): {what}\nExcerpt:\n{ex[:1500]}")
        body = "\n\n".join(blocks)
        try:
            out = llm.chat_json(VERIFY_PROMPT, body, VERIFY_SCHEMA, "meeting_verify", max_out=THINK_BUDGET + 1500,
                                num_ctx=_ctx(est_tokens(VERIFY_PROMPT + body) + SYSTEM_TOKENS, THINK_BUDGET + 1500),
                                think=True)
            checks.update({int(c["id"]): c for c in out.get("checks") or [] if isinstance(c, dict) and "id" in c})
        except Exception:  # unchecked: main-pass items stay, scan-only items go
            continue
    keep_dec, keep_act = [], []
    for i, (kind, c) in enumerate(cands):
        chk = checks.get(i)
        if (chk is not None and chk.get("keep") is False) or (chk is None and c.get("_scan")):
            continue
        if kind == "decision":
            keep_dec.append({**c, "decision": chk.get("text") or c["decision"]} if chk else c)
        else:
            keep_act.append({**c, "task": chk.get("text") or c["task"], "owner": chk.get("owner"),
                             "due": chk.get("due") if chk.get("due") is not None else c.get("due")} if chk else c)
    def scan_only(x: Any) -> bool:  # main-pass items sort first when the lists are capped
        return bool(isinstance(x, dict) and x.get("_scan"))

    def untimed(x: Any) -> bool:
        return not (isinstance(x, dict) and _secs(x.get("said_at")) is not None)

    untimed_dec = [d for d in data.get("decisions") or [] if untimed(d) and not scan_only(d)]
    untimed_act = [a for a in data.get("action_items") or [] if untimed(a) and not scan_only(a)]
    dec = sorted(keep_dec + untimed_dec, key=scan_only)[:MAX_DECISIONS]
    act = sorted(keep_act + untimed_act, key=scan_only)[:MAX_ACTIONS]
    return {**data, "decisions": dec, "action_items": act}


def _ctx(prompt_tokens: int, out_tokens: int) -> int:
    return min(CTX_MAX, ((prompt_tokens + out_tokens + 1023) // 1024) * 1024)


def _union(first: list[Any], extra: list[Any], key: str) -> list[Any]:
    """first + the items of extra that are not already there (similar wording); extra ones marked "_scan"."""
    out = list(first)
    for it in extra:
        text = it.get(key) if isinstance(it, dict) else it
        if text and not any(_similar(str(text), str(o.get(key) if isinstance(o, dict) else o)) for o in out):
            out.append({**it, "_scan": True} if isinstance(it, dict) else it)
    return out


def write_up(llm: JsonLLM, data: dict[str, Any], lines: list[str], who: str, head: str) -> dict[str, Any]:
    """Careful mode, last step: outcome + summary + title written from the checked notes and the end of the
    meeting (small, focused context - where a small model writes best). Keeps the first draft if it fails."""
    tail_chars, tail = 0, []
    for ln in reversed(lines):  # the last ~6 minutes or ~5k characters
        tail.insert(0, ln)
        tail_chars += len(ln)
        if tail_chars > 5000:
            break
    def items(key: str, fmt: Callable[[Any], str]) -> str:
        return "\n".join(f"- {fmt(x)}" for x in data.get(key) or [] if x) or "- (none)"
    body = (head.replace("Transcript:", "").strip() + "\n\nKey points:\n" + items("key_points", str)
            + "\n\nDecisions:\n" + items("decisions", lambda d: d.get("decision") if isinstance(d, dict) else d)
            + "\n\nAction items:\n" + items("action_items", lambda a: f"{a.get('task')} (owner: {a.get('owner')}"
                                                                     f", due: {a.get('due')})")
            + "\n\nFirst draft of the outcome: " + str(data.get("outcome") or "")
            + "\n\nEnd of the transcript:\n" + "\n".join(tail))
    prompt = WRITER_PROMPT.format(who=who)
    try:
        out = llm.chat_json(prompt, body, WRITER_SCHEMA, "meeting_writeup", max_out=THINK_BUDGET + 2500,
                            num_ctx=_ctx(est_tokens(prompt + body) + SYSTEM_TOKENS, THINK_BUDGET + 2500), think=True)
    except Exception:
        return data
    return {**data, **{k: v for k, v in out.items() if k in ("outcome", "summary", "title") and str(v or "").strip()}}


def summarize(llm: JsonLLM, meeting: dict[str, Any], segments: list[dict[str, Any]], context: str = "",
              notes: dict[Any, dict[str, Any]] | None = None, should_yield: Callable[[], bool] | None = None,
              on_progress: Callable[[int, int], None] | None = None, careful: bool = True,
              user_name: str = "") -> dict[str, Any]:
    """The meeting's summary dict (MeetingSummary). `notes` caches finished steps across a Yielded.

    fast:    one pass (or parts + merge for long meetings).
    careful: the same, then a recall-focused scan for decisions and commitments (one-pass meetings), a check of
             every decision/action item against the minute where it was said, and a final write-up of outcome
             and summary from the checked notes + the end of the meeting."""
    lines = transcript_lines(meeting, segments)
    if not lines:
        raise ValueError("this meeting has no transcript yet")
    speakers = [sp["name"] for sp in meeting.get("speakers", [])]
    who = f"{user_name} (one of the speakers)" if user_name else "the participants"
    head = f"Meeting: {meeting.get('title', '')}\n{context}".strip() + "\n\nTranscript:\n"
    notes = notes if notes is not None else {}

    def step(i: int, n: int) -> None:
        if should_yield and should_yield():
            raise Yielded
        if on_progress:
            on_progress(i, n)

    text = sectioned(lines, float(meeting.get("duration_s") or 0) / 60)
    single = est_tokens(head + text) <= SINGLE_PASS_TOKENS
    if single:
        total = 4 if careful else 1
        system = ANALYST.format(who=who)
        base = head + text + "\n\n"
        ctx = _ctx(est_tokens(system + base + MAIN_TASK) + SYSTEM_TOKENS, ANSWER_BUDGET + (THINK_BUDGET if careful else 0))
        if "main" not in notes:
            step(0, total)
            notes["main"] = llm.chat_json(system, base + MAIN_TASK, SUMMARY_SCHEMA, "meeting_summary",
                                          max_out=ANSWER_BUDGET + (THINK_BUDGET if careful else 0), num_ctx=ctx,
                                          think=careful)
        data = dict(notes["main"])
        if careful:
            if "scan" not in notes:
                step(1, total)
                try:  # same system prompt + transcript as the main pass: Ollama reuses the cached prefix
                    notes["scan"] = llm.chat_json(system, base + SCAN_TASK, SCAN_SCHEMA, "meeting_scan",
                                                  max_out=ANSWER_BUDGET, num_ctx=ctx)
                except Exception:
                    notes["scan"] = {}
            data["decisions"] = _union(data.get("decisions") or [], notes["scan"].get("decisions") or [], "decision")
            data["action_items"] = _union(data.get("action_items") or [], notes["scan"].get("action_items") or [], "task")
    else:
        parts = chunks(lines, int(CHUNK_TOKENS * CHARS_PER_TOKEN))
        total = len(parts) + (3 if careful else 1)
        for i, part in enumerate(parts):
            if i in notes:
                continue
            step(i, total)
            prompt = PART_PROMPT.format(i=i + 1, n=len(parts))
            notes[i] = llm.chat_json(prompt, head + part, NOTES_SCHEMA, "meeting_notes", max_out=ANSWER_BUDGET,
                                     num_ctx=_ctx(est_tokens(prompt + head + part) + SYSTEM_TOKENS, ANSWER_BUDGET))
        if "merge" not in notes:
            step(len(parts), total)
            merged = "\n\n".join(_notes_text(i + 1, len(parts), parts[i], notes[i]) for i in range(len(parts)))
            prompt = MERGE_PROMPT.format(who=who)
            body = head.replace("Transcript:", "Notes of each part:") + merged
            out_budget = ANSWER_BUDGET + (THINK_BUDGET if careful else 0)
            notes["merge"] = llm.chat_json(prompt, body, SUMMARY_SCHEMA, "meeting_summary", max_out=out_budget,
                                           num_ctx=_ctx(est_tokens(prompt + body) + SYSTEM_TOKENS, out_budget),
                                           think=careful)
        data = dict(notes["merge"])
    if careful:
        step(total - 2, total)
        data = verify(llm, lines, data)
        step(total - 1, total)
        data = write_up(llm, data, lines, who, head)
    if on_progress:
        on_progress(total, total)
    return clean(data, meeting.get("title", ""), speakers)
