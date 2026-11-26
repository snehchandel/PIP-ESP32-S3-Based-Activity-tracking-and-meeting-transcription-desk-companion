"""Transcript clean-up: what was meant, not every "um" (ADR-033).

Applied to every Whisper result (meetings and voice commands) when Settings -> Meetings -> "Clean up filler words"
is on (the default). The raw text of meeting lines is kept in the database (`meeting_segments.raw_text`).

Conservative on purpose - it only removes what never carries meaning:
- hesitation sounds: um, uh, er, erm, ah, hmm, mm-hmm ("Mm-hmm." on its own is a nod and is dropped too);
- stutters and repeated words: "the the" -> "the", "I, I" -> "I", "no, no, no, no" -> "no" (not "had had",
  and not "that that's", which is grammatical);
- spoken fillers only when set off by commas: ", you know," / ", I mean," / ", like," and a leading "So, um,";
- the user's own vocabulary gets its spelling back ("sfmc" -> "SFMC").
"kind of" / "sort of" / "like" without commas stay: they are often real words ("the kind of data")."""
from __future__ import annotations

import re

_HESITATION = r"(?:u+h+m*|u+m+|e+r+m*|e+h+|a+h+|h+u*m+|m+-?h+m+|uh-huh|mhm)"
_BETWEEN = re.compile(rf",\s*{_HESITATION}\s*,\s*", re.I)  # "the, uh, deck" -> "the deck"
_FILLER = re.compile(rf"(?<![\w'’-]){_HESITATION}(?![\w'’-])[,.]?\s*", re.I)
_REPEAT = re.compile(r"\b(?!had\b)([\w'’]+)(?:,?\s+\1\b(?!['’]))+", re.I)
_SPOKEN = re.compile(r",\s*(?:you know|i mean|like|you see|basically)\s*,", re.I)
_LEAD = re.compile(r"^(?:so|well|okay|ok)\s*,\s*(?:so|well)\s*,\s*", re.I)


def clean_text(text: str, vocabulary: list[str] | None = None) -> str:
    """One line of transcript, cleaned. Returns "" when nothing but hesitation was said."""
    out = _BETWEEN.sub(" ", text)
    out = _FILLER.sub("", out)
    out = _SPOKEN.sub(",", out)
    for _ in range(2):  # "the the the" and "I, I, I" in one go, then whatever filler removal exposed
        out = _REPEAT.sub(lambda m: m.group(1), out)
    out = _LEAD.sub("", out.strip())
    out = re.sub(r"\s+([,.?!])", r"\1", out)          # "word ," -> "word,"
    out = re.sub(r"([,.?!])(?:\s*,)+", r"\1", out)     # ". ," / ",," left behind
    out = re.sub(r"^[,.\s]+", "", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    for w in vocabulary or []:
        if w and not w.islower():
            out = re.sub(rf"(?<![\w-]){re.escape(w)}(?![\w-])", w, out, flags=re.I)
    if out and out[0].islower() and text.strip()[:1].isupper():
        out = out[0].upper() + out[1:]                  # the line started with "Um, so we..." -> "So we..."
    return "" if not re.search(r"\w", out) else out
