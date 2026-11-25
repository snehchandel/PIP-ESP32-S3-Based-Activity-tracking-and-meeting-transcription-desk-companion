"""Which activity did the user name right after the wake word? ("Hi ESP... Meeting", "Hi ESP, alarms, wake me at 7")

The name must open the utterance and stand on its own - followed by a pause (punctuation in Whisper's text) or
nothing at all - so "Meeting with Bob is at 3" stays a brain dump about a meeting instead of starting a recording.
A few fillers and a transcribed wake word in front are skipped."""
from __future__ import annotations

import re

import numpy as np

# activity -> spoken forms (longest first inside the regex)
NAMES: dict[str, tuple[str, ...]] = {
    "MEETING": ("record a meeting", "record the meeting", "record meeting", "start a meeting", "meeting mode",
                "a meeting", "meeting", "meetings"),
    "BRAIN_DUMP": ("brain dump", "brain-dump", "braindump", "brain dumb", "brain"),
    "CALENDAR": ("my calendar", "the calendar", "calendar"),
    "FOCUS": ("focus mode", "focus"),
    "ALARMS": ("an alarm", "alarms", "alarm"),
}
_FILLER = r"(?:um+|uh+|er+|ah+|okay|ok|so|hey|hi|hello|and|right|please|pip|jarvis|computer|joy|e\.?\s?s\.?\s?p\.?)"
_FORMS = sorted(((form, act) for act, forms in NAMES.items() for form in forms), key=lambda x: -len(x[0]))
_ACT_OF = {form: act for form, act in _FORMS}
_RX = re.compile(r"^\W*(?:" + _FILLER + r"\W+)*(?P<name>" + "|".join(re.escape(f) for f, _ in _FORMS) + r")"
                 r"(?P<stop>[.,!?;:…-]+|\s*$)\s*(?P<rest>.*)$", re.I | re.S)


def parse(text: str) -> tuple[str | None, str]:
    """(activity or None, the rest of what was said). The rest is the message for that activity."""
    m = _RX.match(text.strip())
    if not m:
        return None, text.strip()
    return _ACT_OF[m.group("name").lower()], m.group("rest").strip()


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def ends_quiet(pcm16: bytes, tail_s: float = 0.4) -> bool:
    """True if the last `tail_s` of the clip is a pause (so a name at the end of a partial transcript was said on
    its own, not the first word of a longer sentence still being spoken)."""
    x = np.frombuffer(pcm16, dtype="<i2").astype(np.float32)
    n = int(tail_s * 16000)
    if len(x) < 3 * n:
        return False
    frames = x[: len(x) // 320 * 320].reshape(-1, 320)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    loud = float(np.percentile(rms, 90))
    tail = float(np.sqrt((x[-n:] ** 2).mean()))
    return loud > 0 and tail < 0.25 * loud
