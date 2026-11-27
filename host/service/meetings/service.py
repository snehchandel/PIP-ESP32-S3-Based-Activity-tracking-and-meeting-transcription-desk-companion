"""Meeting recorder + transcriber.

Recording: PIP streams its mic (AUDIO_START activity 4 = MEETING) for as long as the meeting runs. Every chunk
is appended to data/meetings/<id>.wav as it arrives, so nothing is held in memory and a crash loses nothing
already received; chunks lost to a link drop are filled with silence (the timeline stays true).

Transcription runs on this PC in a background thread with its own faster-whisper instance (voice commands
never wait behind a long meeting): 10-minute windows cut at quiet moments -> timed segments -> voice features
-> speakers (diarize.py) -> remembered voices name the speakers they recognise; the rest are "Speaker 01..."
until the user names them in the app.

Then, by default, the summary is made on this PC too (local AI, summarize.py) and the meeting is written to the
Obsidian vault (obsidian.py). One worker thread runs both kinds of job, so they never compete for the GPU/CPU:
  - transcriptions always go first; a summary waits until no transcription is queued, and between two parts of a
    long meeting it steps aside (keeping the parts already done) when a new transcription arrives;
  - a voice command being captured or transcribed (Whisper on the same GPU) pauses summaries the same way;
  - the meeting's Whisper model is unloaded before a summary and the local AI model before a transcription, so
    only one big model holds memory at a time.
Kimi summaries (on request) are remote and run at once."""
from __future__ import annotations

import json
import logging
import queue
import struct
import threading
import time
import wave
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from .. import errors
from ..calendar.agenda import day_items
from ..planner.step_templates import steps_for
from ..speech.cleanup import clean_text
from ..speech.stt import SpeechToText
from ..state.manager import DeviceStateManager
from . import actions as act_mod
from . import ask as ask_mod
from . import diarize
from .export import FORMATS, filename, render
from .graph import topic_catalog
from .handoff import handoff_md, parse_summary_md
from .local_ai import LocalAI, LocalAIError
from .obsidian import ObsidianVault
from .store import MeetingRepo, speaker_label
from .summarize import Yielded, clean
from .summarize import summarize as summarize_local
from .voice_embed import VoiceEmbedder

log = logging.getLogger("pip.meetings")
SR = 16000
CHUNK_BYTES = 640               # one 20 ms device audio chunk
WINDOW_S = 600.0                # transcribe in 10 minute windows...
CUT_SEARCH_S = 30.0             # ...cut at the quietest moment of the window's last 30 s
STALE_RECORDING_S = 180.0       # no audio for this long: the device is gone, keep what we have
UPGRADE_JOB = "~voiceprints"      # worker job: old MFCC voiceprints -> the speaker model
MAX_GAP_CHUNKS = 30000          # a seq jump larger than this (10 min) is a restart, not lost audio
VOICE_WAIT_S = 300.0            # a summary waits at most this long for a voice command to finish
IDLE_EXIT_S = 30.0              # the worker frees Whisper and exits after this long with nothing to do
SUMMARY_MODES = ("local", "kimi", "off")
Notify = Callable[[str, dict[str, Any]], None]


def wav_header(data_bytes: int) -> bytes:
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, SR, SR * 2, 2, 16) + b"data" + struct.pack("<I", data_bytes))


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Recording:
    def __init__(self, mid: str, path: Path) -> None:
        self.mid = mid
        self.path = path
        self.f = path.open("wb")
        self.f.write(wav_header(0))
        self.bytes = 0
        self.next_seq: int | None = None
        self.gap_chunks = 0
        self.last_rx = time.monotonic()
        self.lock = threading.Lock()

    def write(self, seq: int | None, pcm: bytes) -> None:
        with self.lock:
            if self.f.closed:
                return
            if seq is not None and self.next_seq is not None:
                gap = (seq - self.next_seq) & 0xFFFF
                if 0 < gap <= MAX_GAP_CHUNKS:  # chunks lost while the link was down: keep the timeline true
                    self.f.write(bytes(gap * CHUNK_BYTES))
                    self.bytes += gap * CHUNK_BYTES
                    self.gap_chunks += gap
            if seq is not None:
                self.next_seq = (seq + 1) & 0xFFFF
            self.f.write(pcm)
            self.bytes += len(pcm)
            self.last_rx = time.monotonic()

    def close(self) -> float:
        with self.lock:
            if not self.f.closed:
                self.f.seek(0)
                self.f.write(wav_header(self.bytes))
                self.f.close()
            return self.bytes / (SR * 2)


def _resample(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == SR or not len(x):
        return x
    n = int(round(len(x) * SR / rate))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


def decode_to_pcm16(src: Path) -> bytes:
    """Any audio file -> mono 16 kHz PCM16 bytes. Plain WAV is read directly; other formats go through PyAV."""
    try:
        with wave.open(str(src), "rb") as w:
            width, ch, rate = w.getsampwidth(), w.getnchannels(), w.getframerate()
            raw = w.readframes(w.getnframes())
        if width != 2:
            raise wave.Error("only 16-bit WAV is read directly")
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, ch).mean(axis=1)
        return np.clip(_resample(x, rate), -32768, 32767).astype("<i2").tobytes()
    except (wave.Error, EOFError):
        pass
    import av  # faster-whisper's own dependency

    out: list[np.ndarray] = []
    with av.open(str(src)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError("the file has no audio track")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SR)
        for frame in container.decode(stream):
            for f in resampler.resample(frame):
                out.append(f.to_ndarray().reshape(-1))
        for f in resampler.resample(None):
            out.append(f.to_ndarray().reshape(-1))
    return np.concatenate(out).astype("<i2").tobytes() if out else b""


def finalize_wav(path: Path) -> float:
    """Repair the header of a WAV whose recording never finished (host crash); returns its duration."""
    size = path.stat().st_size if path.exists() else 0
    data = max(0, size - 44)
    data -= data % 2
    if path.exists():
        with path.open("r+b") as f:
            f.write(wav_header(data))
    return data / (SR * 2)


def end_sentences(segments: list[dict[str, Any]]) -> None:
    """large-v3-turbo often leaves the full stop off a line ("...for SMS CASL" / "Well, maybe..."). Add it when the next
    line starts a new sentence (capital letter) or it is the last line; a line that runs on stays open."""
    for i, s in enumerate(segments):
        text = s["text"].rstrip()
        nxt = segments[i + 1]["text"].lstrip() if i + 1 < len(segments) else ""
        if text and text[-1].isalnum() and (not nxt or nxt[:1].isupper()):
            s["text"] = text + "."


class MeetingService:
    def __init__(self, manager: DeviceStateManager, data_dir: Path, model_name: str, notify: Notify,
                 summarizer: Callable[[], Any] | None = None, stt: SpeechToText | None = None,
                 local_ai: LocalAI | None = None, summary_mode: Callable[[], str] = lambda: "off",
                 vault: Callable[[], ObsidianVault | None] = lambda: None,
                 vocabulary: Callable[[], list[str]] | None = None,
                 voice_busy: Callable[[], bool] = lambda: False,
                 summary_quality: Callable[[], str] = lambda: "careful",
                 my_name: Callable[[], str] = lambda: "",
                 refine_task: Callable[[str, str], None] = lambda tid, title: None,
                 cleanup: Callable[[], bool] = lambda: True,
                 voiceprints: VoiceEmbedder | None = None) -> None:
        self.m = manager
        self.repo = MeetingRepo(manager.db)
        self.dir = data_dir / "meetings"
        self.stt = stt or SpeechToText(model_name)
        self.notify = notify
        self.summarizer = summarizer  # -> a planner with summarize_meeting(text) (Kimi, budget-checked)
        self.local_ai = local_ai      # Ollama on this PC: the default summariser
        self.summary_mode = summary_mode  # "local" (default in the app) | "kimi" | "off": after each transcription
        self.vault = vault            # the Obsidian vault to write meetings into, or None
        self.vocabulary = vocabulary or (lambda: list(getattr(self.stt, "vocabulary", [])))
        self.voice_busy = voice_busy  # a voice command is being captured / transcribed right now
        self.summary_quality = summary_quality  # "careful" (default: think + check + write-up) | "fast"
        self.my_name = my_name        # the user's name as a speaker: whose action items are "mine"
        self.refine_task = refine_task  # a task made from an action item gets Kimi's steps (like any new task)
        self.cleanup = cleanup        # drop fillers and stutters from transcript lines (raw text is kept)
        self.voiceprints = voiceprints  # neural speaker model (ADR-038); None or missing file = MFCC features
        self._vp_checked = False
        self._rec: dict[int, _Recording] = {}
        self._q: queue.Queue[tuple[str, int | None]] = queue.Queue()  # transcriptions (always first)
        self._sq: list[str] = []      # local summaries waiting for the transcriptions to finish
        self._partial: dict[str, dict[int, dict[str, Any]]] = {}  # parts of long meetings already summarised
        self._sum_progress: dict[str, tuple[int, int]] = {}
        self._wake = threading.Event()
        self._worker: threading.Thread | None = None
        self._busy = ""
        self._busy_kind = ""
        self._llm_warm = False        # the local AI model may still be in (V)RAM
        self._lock = threading.RLock()
        self._vault_lock = threading.Lock()

    # ---- recording (device link thread) -------------------------------------------------------------
    def default_title(self, start: datetime) -> str:
        """The calendar item around the start time names the meeting; else "Meeting · Tue Nov 24, 14:32"."""
        local = start.astimezone(self.m.tz)
        try:
            items = day_items(self.m.tasks.list_tasks(local.date().isoformat(), local.date().isoformat()),
                              self.m.tasks.reminders(), [], local.date(), self.m.tz)
            mins = local.hour * 60 + local.minute
            near = [(abs(int(i["hhmm"][:2]) * 60 + int(i["hhmm"][3:]) - mins), i["title"]) for i in items
                    if i["hhmm"] and i["kind"] in (0, 1)
                    and -20 <= mins - (int(i["hhmm"][:2]) * 60 + int(i["hhmm"][3:])) <= 45]
            if near:
                return str(min(near)[1])[:80]
        except Exception:  # a calendar hiccup must never stop a recording
            log.exception("calendar lookup for the meeting title failed")
        return f"Meeting · {local.strftime('%a %b')} {local.day}, {local.strftime('%H:%M')}"

    def start(self, stream_id: int, started: datetime | None = None) -> str:
        started = started or datetime.now(UTC)
        self.dir.mkdir(parents=True, exist_ok=True)
        mid = self.repo.create(self.default_title(started), utc_iso(started), self.m.tz.key, "")
        path = self.dir / f"{mid}.wav"
        self.repo.update(mid, audio_path=str(path))
        with self._lock:
            for old_sid, old in list(self._rec.items()):  # a new meeting while one is "open": the old one ended
                self._finish(old_sid, old)
            self._rec[stream_id] = _Recording(mid, path)
        with self.m.lock:  # a focus step waits while the meeting runs
            if self.m.timer.state == "RUNNING":
                self.m.timer_pause()
        log.info("meeting %s recording (stream %d)", mid, stream_id)
        self.notify("meeting_updated", {"id": mid, "status": "RECORDING"})
        return mid

    def owns(self, stream_id: int) -> bool:
        return stream_id in self._rec

    def data(self, stream_id: int, pcm: bytes, seq: int | None = None) -> None:
        rec = self._rec.get(stream_id)
        if rec is not None:
            rec.write(seq, pcm)

    def end(self, stream_id: int) -> str | None:
        with self._lock:
            rec = self._rec.get(stream_id)
            if rec is None:
                return None
            return self._finish(stream_id, rec)

    def _finish(self, stream_id: int, rec: _Recording) -> str:
        self._rec.pop(stream_id, None)
        dur = rec.close()
        started = self.repo.get(rec.mid)
        ended = datetime.now(UTC)
        if started:  # wall-clock end = start + audio length (gaps included), robust to late END frames
            ended = datetime.fromisoformat(started["started_at"].replace("Z", "+00:00")) + timedelta(seconds=dur)
        self.repo.update(rec.mid, status="QUEUED", duration_s=round(dur, 2), ended_at=utc_iso(ended),
                         gaps_s=round(rec.gap_chunks * 0.02, 2))
        log.info("meeting %s recorded: %.0f s (%.1f s lost to link drops)", rec.mid, dur, rec.gap_chunks * 0.02)
        self.notify("meeting_updated", {"id": rec.mid, "status": "QUEUED"})
        self.enqueue(rec.mid)
        return rec.mid

    def recording(self) -> list[dict[str, Any]]:
        out = []
        for rec in list(self._rec.values()):
            m = self.repo.get(rec.mid)
            if m:
                m["recorded_s"] = round(rec.bytes / (SR * 2), 1)
                out.append(m)
        return out

    def tick(self) -> None:
        """~1 Hz: a recording whose device went silent for minutes is closed and transcribed."""
        with self._lock:
            for sid, rec in list(self._rec.items()):
                if time.monotonic() - rec.last_rx > STALE_RECORDING_S:
                    log.warning("meeting %s: no audio for %.0f s, closing it", rec.mid, STALE_RECORDING_S)
                    self._finish(sid, rec)

    def recover(self) -> None:
        """At startup: finish recordings interrupted by a host restart, resume unfinished transcriptions."""
        for m in self.repo.with_status("RECORDING"):
            dur = finalize_wav(Path(m["audio_path"]))
            start = datetime.fromisoformat(m["started_at"].replace("Z", "+00:00"))
            self.repo.update(m["id"], status="QUEUED", duration_s=round(dur, 2),
                             ended_at=utc_iso(start + timedelta(seconds=dur)))
        for m in self.repo.with_status("QUEUED", "TRANSCRIBING"):
            self.enqueue(m["id"])
        for m in self.repo.with_status("READY"):
            if m.get("summary_status") in ("QUEUED", "SUMMARIZING"):  # interrupted by a restart: do it again
                if self.summary_mode() == "local" and self.local_ai is not None:
                    self.enqueue_summary(m["id"])
                else:
                    self.repo.update(m["id"], summary_status="NONE")
        if self.repo.index_is_empty():  # meetings from before search existed
            for m in self.repo.with_status("READY"):
                self.repo.reindex(m["id"])

    # ---- import ---------------------------------------------------------------------------------------
    def import_audio(self, src: Path, title: str, started: datetime | None = None) -> str:
        """Transcribe an existing recording (WAV, or anything PyAV reads: mp3, m4a...) as 16 kHz mono WAV."""
        pcm = decode_to_pcm16(src)
        if not pcm:
            raise ValueError("no audio in that file")
        started = started or datetime.now(UTC)
        self.dir.mkdir(parents=True, exist_ok=True)
        mid = self.repo.create(title or self.default_title(started), utc_iso(started), self.m.tz.key, "",
                               source="IMPORT", status="QUEUED")
        path = self.dir / f"{mid}.wav"
        path.write_bytes(wav_header(len(pcm)) + pcm)
        dur = len(pcm) / (SR * 2)
        self.repo.update(mid, audio_path=str(path), duration_s=round(dur, 2),
                         ended_at=utc_iso(started + timedelta(seconds=dur)))
        self.enqueue(mid)
        return mid

    # ---- transcription worker -------------------------------------------------------------------------
    def enqueue(self, mid: str, num_speakers: int | None = None) -> None:
        self._q.put((mid, num_speakers))
        self._kick()

    def enqueue_summary(self, mid: str) -> None:
        """Summarise on this PC once no transcription is waiting (re-queuing a queued meeting is a no-op)."""
        with self._lock:
            if mid not in self._sq:
                self._sq.append(mid)
        self.repo.update(mid, summary_status="QUEUED", summary_error=None)
        self.notify("meeting_updated", {"id": mid, "status": "READY", "summary_status": "QUEUED"})
        self._kick()

    def _kick(self) -> None:
        with self._lock:
            self._wake.set()
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="pip-meetings", daemon=True)
                self._worker.start()

    def wait_idle(self, timeout: float = 600.0) -> bool:
        """Tests: block until every transcription and summary is processed."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                if self._q.unfinished_tasks == 0 and not self._sq and not self._busy:
                    return True
            time.sleep(0.05)
        return False

    def _run(self) -> None:
        while True:
            try:
                mid, n = self._q.get_nowait()
            except queue.Empty:
                mid = ""
            if mid == UPGRADE_JOB:
                self._run_upgrade()
                continue
            if mid:
                self._run_transcription(mid, n)
                continue
            with self._lock:
                smid = self._sq[0] if self._sq else ""
            if smid:
                self._run_summary(smid)
                continue
            if not self._wake.wait(IDLE_EXIT_S):
                with self._lock:
                    if self._q.empty() and not self._sq:
                        self.stt.unload()  # give the memory back until the next meeting
                        self._worker = None
                        return
            self._wake.clear()

    def _run_transcription(self, mid: str, n: int | None) -> None:
        try:
            self._busy, self._busy_kind = mid, "transcribe"
            if self._llm_warm and self.local_ai is not None:
                self.local_ai.unload()  # Whisper gets the GPU memory the summariser held
                self._llm_warm = False
            self.transcribe(mid, n)
        except Exception as e:
            errors.report(self.m.db, "meetings", "Meeting transcription failed", str(e), e, meeting=mid)
            self.repo.update(mid, status="FAILED", error=str(e)[:300])
            self.notify("meeting_updated", {"id": mid, "status": "FAILED"})
        finally:
            self._busy = self._busy_kind = ""
            self._q.task_done()

    def _run_summary(self, mid: str) -> None:
        """One local summary job. Leaves it queued (Yielded) when a transcription or a voice command needs the
        machine; the parts already summarised are kept in `_partial`."""
        waited = 0.0
        while self.voice_busy() and self._q.empty() and waited < VOICE_WAIT_S:
            time.sleep(0.25)
            waited += 0.25
        if not self._q.empty():
            return  # transcription first; this summary stays at the head of its queue
        patient = waited < VOICE_WAIT_S  # a voice capture that never ends must not stall summaries forever

        def done() -> None:
            with self._lock:
                if mid in self._sq:
                    self._sq.remove(mid)
            self._partial.pop(mid, None)
            self._sum_progress.pop(mid, None)

        m = self.repo.get(mid)
        if m is None or m["status"] != "READY" or self.local_ai is None:
            if m is not None and m["status"] == "READY":
                self.repo.update(mid, summary_status="FAILED", summary_error="local AI is not set up")
                self.notify("meeting_updated", {"id": mid, "status": "READY", "summary_status": "FAILED"})
            done()
            return
        self._busy, self._busy_kind = mid, "summarize"
        try:  # the job leaves the queue only once its result is stored (wait_idle / status stay truthful)
            self._summary_job(mid, m, patient)
        except Yielded:
            log.info("meeting %s: summary paused after %d part(s) for more urgent work", mid,
                     len(self._partial.get(mid, {})))
            self.repo.update(mid, summary_status="QUEUED")
            self.notify("meeting_updated", {"id": mid, "status": "READY", "summary_status": "QUEUED"})
            return
        except Exception as e:
            if isinstance(e, LocalAIError):
                log.warning("meeting %s: local summary failed: %s", mid, e)
            else:
                errors.report(self.m.db, "meetings", "Meeting summary failed", str(e), e, meeting=mid)
            self.repo.update(mid, summary_status="FAILED", summary_error=str(e)[:300])
            self.notify("meeting_updated", {"id": mid, "status": "READY", "summary_status": "FAILED"})
            self.touched(mid)  # the vault still gets the meeting, without a summary
            done()
            return
        finally:
            self._busy = self._busy_kind = ""
        done()

    def _summary_job(self, mid: str, m: dict[str, Any], patient: bool) -> None:
        assert self.local_ai is not None
        self.local_ai.check_ready()
        self.stt.unload()  # the meeting Whisper model is reloaded for the next transcription
        self.repo.update(mid, summary_status="SUMMARIZING", summary_error=None)
        self.notify("meeting_updated", {"id": mid, "status": "READY", "summary_status": "SUMMARIZING"})

        def progress(i: int, n: int) -> None:
            self._sum_progress[mid] = (i, n)
            self.notify("meeting_updated", {"id": mid, "status": "READY", "summary_status": "SUMMARIZING",
                                            "summary_part": i, "summary_parts": n})

        self._llm_warm = True
        data = summarize_local(self.local_ai, m, self.repo.segments(mid), self._context(m),
                               notes=self._partial.setdefault(mid, {}),
                               should_yield=lambda: not self._q.empty() or (patient and self.voice_busy()),
                               on_progress=progress, careful=self.summary_quality() != "fast",
                               user_name=self.my_name())
        self._save_summary(mid, data, self.local_ai.engine)
        log.info("meeting %s summarised on this PC (%s)", mid, self.local_ai.engine)

    def _context(self, m: dict[str, Any]) -> str:
        people = [sp["name"] for sp in m.get("speakers", [])]
        words = self.vocabulary()
        day = act_mod.meeting_day(m)
        return "\n".join(x for x in (f"Speakers: {', '.join(people)}" if people else "",
                                     f"Spellings of names and terms: {', '.join(words)}" if words else "",
                                     f"Meeting date: {day.strftime('%A %Y-%m-%d')}",
                                     self._known_topics(m)) if x)

    def _known_topics(self, m: dict[str, Any]) -> str:
        """The topic names earlier summaries used (graph.topic_catalog), so this summary joins them (ADR-037)."""
        try:
            others = [x for x in self.repo.all_with_summaries() if x["id"] != m["id"]]
            names = topic_catalog(others, [p["name"] for p in self.repo.profiles()])
        except Exception as e:  # never let the hint stop a summary
            log.warning("topic catalog failed: %s", e)
            return ""
        return f"Topics already used in earlier meetings: {'; '.join(names)}" if names else ""

    def _read(self, path: Path, start_s: float, end_s: float) -> np.ndarray:
        a, b = int(start_s * SR), int(end_s * SR)
        raw = np.fromfile(path, dtype="<i2", count=max(0, b - a), offset=44 + 2 * a)
        return raw.astype(np.float32) / 32768.0

    @staticmethod
    def _quiet_cut(audio: np.ndarray, at_s: float) -> float:
        """The quietest 100 ms in the CUT_SEARCH_S before `at_s` (relative to `audio`), so no word is cut."""
        lo = max(0, int((at_s - CUT_SEARCH_S) * SR))
        hi = min(len(audio), int(at_s * SR))
        seg = audio[lo:hi]
        n = len(seg) // 1600
        if n < 2:
            return at_s
        rms = (seg[: n * 1600].reshape(n, 1600) ** 2).mean(axis=1)
        return (lo + int(np.argmin(rms)) * 1600 + 800) / SR

    def transcribe(self, mid: str, num_speakers: int | None = None) -> None:
        m = self.repo.get(mid)
        if m is None:
            return
        path = Path(m["audio_path"])
        total = max(0.0, (path.stat().st_size - 44) / (SR * 2)) if path.exists() else 0.0
        if total <= 0:
            raise RuntimeError("the recording is empty")
        self.repo.update(mid, status="TRANSCRIBING", progress=0.0, error=None)
        self.notify("meeting_updated", {"id": mid, "status": "TRANSCRIBING", "progress": 0.0})
        segments: list[dict[str, Any]] = []
        pos = 0.0
        last_note = 0.0
        while pos < total - 0.3:
            end = min(total, pos + WINDOW_S)
            audio = self._read(path, pos, min(total, end + 1.0))
            if end < total:
                end = pos + self._quiet_cut(audio, end - pos)
                audio = audio[: int((end - pos) * SR)]

            def progress(seg_end: float, base: float = pos) -> None:
                nonlocal last_note
                frac = min(0.99, (base + seg_end) / total)
                if frac - last_note >= 0.02:
                    last_note = frac
                    self.repo.update(mid, progress=round(frac, 3))
                    self.notify("meeting_updated", {"id": mid, "status": "TRANSCRIBING", "progress": round(frac, 3)})

            tidy = self.cleanup()
            vocab = self.vocabulary()
            for s0, s1, raw in self.stt.transcribe_segments(audio, progress):
                text = clean_text(raw, vocab) if tidy else raw
                if not text:  # nothing but "um" / "mm-hmm"
                    continue
                feats = self.voiceprint(audio[int(s0 * SR): int(s1 * SR)])
                segments.append({"start_s": round(pos + s0, 2), "end_s": round(pos + s1, 2), "text": text,
                                 "raw_text": raw if text != raw else None,
                                 "embedding": [round(float(x), 5) for x in feats] if feats is not None else None})
            pos = end
        end_sentences(segments)
        self._assign_speakers(mid, segments, num_speakers)
        self._partial.pop(mid, None)  # a new transcript: parts summarised from an old one are stale
        self.repo.update(mid, status="READY", progress=1.0, duration_s=round(total, 2))
        log.info("meeting %s transcribed: %d segments", mid, len(segments))
        self.notify("meeting_updated", {"id": mid, "status": "READY", "progress": 1.0})
        self._auto_summary(mid)
        self.touched(mid)

    def _auto_summary(self, mid: str) -> None:
        """After a transcription: summarise as Settings say - on this PC (default), with Kimi, or not at all."""
        mode = self.summary_mode()
        if mode == "local" and self.local_ai is not None:
            self.enqueue_summary(mid)
        elif mode == "kimi" and self.summarizer is not None:
            def run() -> None:
                try:
                    self.summarize(mid, "kimi")
                except Exception as e:  # shown on the meeting; the transcript is fine
                    self.repo.update(mid, summary_status="FAILED", summary_error=str(e)[:300])
                    self.notify("meeting_updated", {"id": mid, "status": "READY", "summary_status": "FAILED"})
                    self.touched(mid)
            self.repo.update(mid, summary_status="QUEUED", summary_error=None)
            threading.Thread(target=run, name="pip-meeting-kimi", daemon=True).start()

    # ---- voiceprints (ADR-038) ------------------------------------------------------------------------
    def neural_ready(self) -> bool:
        """The speaker model is on disk (fetched once, on the worker thread, before the first use)."""
        if self.voiceprints is None:
            return False
        if not self._vp_checked:
            self._vp_checked = True
            self.voiceprints.fetch()
        return self.voiceprints.available()

    def voiceprint(self, audio: np.ndarray) -> np.ndarray | None:
        if self.neural_ready():
            try:
                return self.voiceprints.embed(audio)  # type: ignore[union-attr]
            except Exception as e:  # a broken model file must not lose the transcript
                log.warning("speaker model failed (%s) - using MFCC features", e)
                self.voiceprints = None
        return diarize.voice_features(audio)

    def upgrade_voiceprints(self) -> None:
        """Queue the one-time upgrade of old (MFCC) voiceprints to the speaker model's, after transcriptions."""
        if self.voiceprints is not None:
            self._q.put((UPGRADE_JOB, None))
            self._kick()

    def _run_upgrade(self) -> None:
        try:
            self._busy, self._busy_kind = UPGRADE_JOB, "voiceprints"
            n = self.reembed_all()
            if n:
                log.info("voiceprints upgraded for %d meetings", n)
        except Exception as e:
            errors.report(self.m.db, "meetings", "Voiceprint upgrade failed", str(e), e)
        finally:
            self._busy = self._busy_kind = ""
            self._q.task_done()

    def reembed_all(self) -> int:
        """Recompute every stored line's voiceprint from the recording with the speaker model, keeping the
        transcript, the speakers and the names the user gave; then rebuild each remembered voice from the lines
        of the speakers it names. Meetings already done (or whose audio is gone) are skipped. Returns how many
        meetings changed."""
        if not self.neural_ready():
            return 0
        dim = self.voiceprints.dim  # type: ignore[union-attr]
        done = 0
        for m in self.repo.list():
            segs = self.repo.segments(m["id"], with_embeddings=True)
            path = Path(m.get("audio_path") or "")
            if not segs or not path.exists() or all(s["embedding"] and len(s["embedding"]) == dim for s in segs):
                continue
            total = max(0.0, (path.stat().st_size - 44) / (SR * 2))
            audio = self._read(path, 0.0, total)
            rows = []
            for s in segs:
                v = self.voiceprint(audio[int(s["start_s"] * SR): int(s["end_s"] * SR)])
                rows.append((s["id"], [round(float(x), 5) for x in v] if v is not None else None))
            self.repo.set_embeddings(rows)
            done += 1
        if done:
            for p in self.repo.profiles():
                lines = [s for s in self.repo.profile_segments(p["id"]) if len(s["embedding"]) == dim]
                if lines:
                    w = np.array([max(0.1, s["end_s"] - s["start_s"]) for s in lines])
                    emb = (np.array([s["embedding"] for s in lines]) * w[:, None]).sum(0) / w.sum()
                    self.repo.set_profile_embedding(p["id"], [round(float(x), 5) for x in emb], len(lines))
        return done

    def _assign_speakers(self, mid: str, segments: list[dict[str, Any]], num_speakers: int | None) -> None:
        feats = [np.array(s["embedding"]) if s.get("embedding") else None for s in segments]
        d = diarize.diarize(feats, [s["end_s"] - s["start_s"] for s in segments], num_speakers)
        known = diarize.match_profiles(d, self.repo.profiles(with_embeddings=True))
        for s, lab in zip(segments, d.labels, strict=True):
            s["speaker_key"] = f"S{lab + 1}"
        n = max(d.labels) + 1 if d.labels else 0
        speakers = [{"key": f"S{i + 1}", "name": known[i]["name"] if i in known else speaker_label(i + 1),
                     "profile_id": known[i]["id"] if i in known else None, "auto": i in known} for i in range(n)]
        self.repo.replace_transcript(mid, segments, speakers)

    def rediarize(self, mid: str, num_speakers: int | None) -> None:
        """Re-run speaker detection (e.g. with the number of people the user knows were there) - no new
        transcription; names the user gave are kept where a remembered voice matches again."""
        segs = self.repo.segments(mid, with_embeddings=True)
        if not segs:
            raise ValueError("this meeting has no transcript yet")
        self._assign_speakers(mid, segs, num_speakers)
        self.notify("meeting_updated", {"id": mid, "status": "READY"})
        self.touched(mid)

    # ---- review ---------------------------------------------------------------------------------------------
    def speaker_centroid(self, mid: str, key: str) -> tuple[list[float], int] | None:
        rows = [s for s in self.repo.segments(mid, with_embeddings=True) if s["speaker_key"] == key and s["embedding"]]
        if not rows:
            return None
        dims = [len(s["embedding"]) for s in rows]
        dim = max(set(dims), key=dims.count)
        rows = [s for s in rows if len(s["embedding"]) == dim]
        w = np.array([max(0.1, s["end_s"] - s["start_s"]) for s in rows])
        emb = np.array([s["embedding"] for s in rows])
        return ((emb * w[:, None]).sum(0) / w.sum()).tolist(), len(rows)

    def rename_speaker(self, mid: str, key: str, name: str, remember: bool = True) -> dict[str, Any]:
        name = " ".join(name.split())[:60]
        if not name:
            raise ValueError("name is empty")
        profile_id = None
        if remember:
            cen = self.speaker_centroid(mid, key)
            if cen is not None:
                profile_id = self.repo.learn_profile(name, cen[0], cen[1])
        if not self.repo.rename_speaker(mid, key, name, profile_id):
            raise KeyError(key)
        self.notify("meeting_updated", {"id": mid, "status": "READY"})
        self.touched(mid)
        return {"key": key, "name": name, "profile_id": profile_id}

    def summarize(self, mid: str, engine: str = "local") -> dict[str, Any]:
        """engine "local": queue it for the worker (returns at once); "kimi": ask Kimi now (returns the summary)."""
        m = self.repo.get(mid)
        if m is None:
            raise KeyError(mid)
        if not self.repo.segments(mid):
            raise ValueError("this meeting has no transcript yet")
        if engine == "local":
            if self.local_ai is None:
                raise RuntimeError("local AI is not set up")
            self.enqueue_summary(mid)
            return {"queued": True, "summary_status": "QUEUED"}
        if self.summarizer is None:
            raise RuntimeError("no AI configured")
        planner = self.summarizer()
        text = render({**m, "summary": None, "notes": ""}, self.repo.segments(mid), "txt")
        self.repo.update(mid, summary_status="SUMMARIZING", summary_error=None)
        self.notify("meeting_updated", {"id": mid, "status": m["status"], "summary_status": "SUMMARIZING"})
        try:
            topics = self._known_topics(m)
            summary = planner.summarize_meeting((topics + "\n\n" if topics else "") + text[-120_000:])
        except Exception as e:
            self.repo.update(mid, summary_status="FAILED", summary_error=str(e)[:300])
            self.notify("meeting_updated", {"id": mid, "status": m["status"], "summary_status": "FAILED"})
            raise
        data = summary.model_dump() if hasattr(summary, "model_dump") else dict(summary)
        return self._save_summary(mid, clean(data, m["title"]), str(getattr(planner, "model", "kimi")))

    def upload_summary(self, mid: str, text: str, source: str = "") -> dict[str, Any]:
        """A summary written by another AI agent from the "ai" export (handoff.py) becomes this meeting's summary,
        exactly like one made here: action items keep what the user did with them, dates, calendar, Obsidian."""
        m = self.repo.get(mid)
        if m is None:
            raise KeyError(mid)
        if m["status"] != "READY":
            raise RuntimeError("the meeting isn't transcribed yet")
        with self._lock:
            if m.get("summary_status") == "SUMMARIZING":
                raise RuntimeError("PIP is summarising this meeting right now - wait for it to finish, then upload")
            if mid in self._sq:  # a queued local summary would overwrite the uploaded one
                self._sq.remove(mid)
        data = clean(parse_summary_md(text), m["title"], [sp["name"] for sp in m.get("speakers", [])])
        source = " ".join(source.split())[:40]
        return self._save_summary(mid, data, f"upload/{source}" if source else "upload")

    def _save_summary(self, mid: str, data: dict[str, Any], engine: str) -> dict[str, Any]:
        m = self.repo.get(mid)
        if m is None:
            return data
        old = (m.get("summary") or {}).get("action_items") or []
        for a in data.get("action_items") or []:  # a redone summary keeps what the user did with an item
            prev = next((o for o in old if o["task"].strip().lower() == a["task"].strip().lower()), None)
            if prev:
                for k in ("done", "parked", "status", "ref_id"):
                    if prev.get(k) is not None:
                        a[k] = prev[k]
                if prev.get("due_user"):
                    a.update(due_user=True, due_date=prev.get("due_date"), due_time=prev.get("due_time"))
        act_mod.enrich(data, m, self.my_name())
        self.repo.update(mid, summary_json=json.dumps(data), summary_status="READY", summary_engine=engine,
                         summary_error=None)
        if data.get("title") and m["title"].startswith("Meeting · "):
            self.repo.update(mid, title=str(data["title"])[:80])
        self.notify("meeting_updated", {"id": mid, "status": m["status"], "summary_status": "READY"})
        self.touched(mid)
        return data

    # ---- search index + Obsidian vault ------------------------------------------------------------------
    def touched(self, mid: str) -> None:
        """A meeting's transcript, speakers, title, notes or summary changed: refresh search and its vault note."""
        try:
            self.repo.reindex(mid)
        except Exception as e:
            errors.report(self.m.db, "meetings", "Search index update failed", str(e), e, meeting=mid)
        self.sync_vault(mid)

    def sync_vault(self, mid: str, overview: bool = True) -> str | None:
        """Write the meeting into the Obsidian vault (if one is set). Waits while its summary is still coming, so
        the note is born with its final title. Never raises: the vault is a copy, not the source of truth."""
        vault = self.vault()
        if vault is None:
            return None
        m = self.repo.get(mid)
        if m is None or m["status"] != "READY" or m.get("summary_status") in ("QUEUED", "SUMMARIZING"):
            return None
        try:
            with self._vault_lock:
                rel, ticked = vault.write_meeting(m, self.repo.segments(mid), self.vocabulary())
                updates: dict[str, Any] = {}
                if rel != m.get("vault_note"):
                    updates["vault_note"] = rel
                summary = m.get("summary")
                if summary and ticked:  # ticked in Obsidian -> done in PIP
                    updates["summary_json"] = json.dumps(summary)
                if updates:
                    self.repo.update(mid, **updates)
                if overview:
                    vault.write_overview(self.repo.all_with_summaries(), datetime.now(self.m.tz))
            return rel
        except Exception as e:
            errors.report(self.m.db, "meetings", "Writing the meeting to Obsidian failed", str(e), e, meeting=mid)
            return None

    def sync_vault_all(self) -> int:
        """Write every finished meeting (after the vault is chosen in Settings). Returns how many were written."""
        vault = self.vault()
        if vault is None:
            return 0
        n = sum(1 for m in self.repo.with_status("READY") if self.sync_vault(m["id"], overview=False))
        try:
            with self._vault_lock:
                vault.write_overview(self.repo.all_with_summaries(), datetime.now(self.m.tz))
        except Exception as e:
            errors.report(self.m.db, "meetings", "Writing the Obsidian index failed", str(e), e)
        return n

    # ---- questions + action items -----------------------------------------------------------------------
    def search(self, q: str, meeting_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return ask_mod.search(self.repo, q, limit, meeting_id)

    def ask(self, question: str, engine: str = "local", meeting_id: str | None = None) -> dict[str, Any]:
        """Answer from the passages that match (see ask.py). Local AI by default; Kimi when asked."""
        if engine == "kimi":
            if self.summarizer is None:
                raise RuntimeError("no AI configured")
            planner = self.summarizer()
            out = ask_mod.ask(self.repo, lambda sys, user: planner.chat_text(sys, user, "meeting_question"),
                              question, meeting_id)
            out["engine"] = str(getattr(planner, "model", "kimi"))
            return out
        if self.local_ai is None:
            raise RuntimeError("local AI is not set up")
        local = self.local_ai
        out = ask_mod.ask(self.repo, lambda sys, user: local.chat_text(sys, user, "meeting_question"), question,
                          meeting_id)
        out["engine"] = local.engine
        return out

    def action_items(self, include_archived: bool = False) -> list[dict[str, Any]]:
        """Every action item of every meeting: undecided first, mine first, newest meeting first."""
        out = []
        for m in self.repo.all_with_summaries():
            if m.get("archived") and not include_archived:
                continue
            for i, a in enumerate((m.get("summary") or {}).get("action_items") or []):
                out.append({**a, "index": i, "meeting_id": m["id"], "meeting": m["title"],
                            "started_at": m["started_at"]})
        return sorted(out, key=lambda a: (bool(a.get("done")), a.get("status", "new") != "new", not a.get("mine")))

    def update_action(self, mid: str, index: int, **fields: Any) -> dict[str, Any]:
        """Edit one action item: task, owner, due_date/due_time (marks it as set by the user), status, done."""
        m = self.repo.get(mid)
        items = ((m or {}).get("summary") or {}).get("action_items") or []
        if m is None or not 0 <= index < len(items):
            raise KeyError(index)
        a = items[index]
        if "due_date" in fields or "due_time" in fields:
            a["due_user"] = True
        for k in ("task", "owner", "due_date", "due_time", "status", "done"):
            if k in fields:
                a[k] = fields[k]
        if "owner" in fields:
            a["mine"] = act_mod.is_mine(a.get("owner"), self.my_name())
        self.repo.update(mid, summary_json=json.dumps(m["summary"]))
        self.notify("meeting_updated", {"id": mid, "status": m["status"]})
        self.touched(mid)
        self.m.changed()  # the calendar shows dated items
        return a

    def convert_actions(self, mid: str, picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Turn chosen action items into a task (on its date, else today), a reminder (date + time, 09:00 when no
        time was said) or a parked tangent. picks: {index, as: task|reminder|park, date?, time?}. Each item is
        converted once; returns what was made."""
        m = self.repo.get(mid)
        items = ((m or {}).get("summary") or {}).get("action_items") or []
        if m is None:
            raise KeyError(mid)
        tz = self.m.tz
        made = []
        for p in picks:
            i, kind = int(p["index"]), str(p["as"])
            if not 0 <= i < len(items) or items[i].get("status", "new") not in ("new", "dismissed"):
                continue
            a = items[i]
            day = str(p.get("date") or a.get("due_date") or datetime.now(tz).date().isoformat())
            hhmm = p.get("time") or a.get("due_time")
            note = f"From meeting '{m['title']}'" + (f" (owner: {a['owner']})" if a.get("owner") else "") + \
                (f" (due: {a['due']})" if a.get("due") else "")
            if kind == "task":
                ref = self.m.tasks.create_task(a["task"][:120], steps_for(a["task"]), day, tz.key, start_hhmm=hhmm or None)
                self.refine_task(ref, a["task"])
            elif kind == "reminder":
                local = datetime.fromisoformat(f"{day}T{hhmm or '09:00'}").replace(tzinfo=tz)
                ref = self.m.tasks.add_reminder(a["task"][:120], utc_iso(local), tz.key, note)
            elif kind == "park":
                ref = self.m.tasks.park(a["task"][:64], f"{note}: {a['task']}")
                a["parked"] = True
            else:
                continue
            a.update(status={"park": "parked"}.get(kind, kind), ref_id=ref)
            if p.get("date"):
                a.update(due_date=day, due_user=True)
            made.append({"index": i, "as": kind, "id": ref})
        if made:
            self.repo.update(mid, summary_json=json.dumps(m["summary"]))
            self.m.changed()
            self.notify("meeting_updated", {"id": mid, "status": m["status"]})
            self.touched(mid)
        return made

    def reenrich_all(self) -> None:
        """"Your name" changed: recompute which action items are mine (dates the user set stay)."""
        for m in self.repo.all_with_summaries():
            if m.get("summary"):
                act_mod.enrich(m["summary"], m, self.my_name())
                self.repo.update(m["id"], summary_json=json.dumps(m["summary"]))
        self.m.changed()

    def clean_existing(self) -> dict[str, int]:
        """Apply the filler/stutter clean-up to transcripts made before it existed (or with it switched off). The
        original words go to raw_text, so this can be undone; lines that were only "um" are removed."""
        vocab = self.vocabulary()
        changed = removed = 0
        for m in self.repo.all_with_summaries():
            n_changed, n_removed = self.repo.clean_segments(m["id"], lambda t: clean_text(t, vocab))
            if n_changed or n_removed:
                changed += n_changed
                removed += n_removed
                self.touched(m["id"])
        return {"lines_changed": changed, "lines_removed": removed}

    def archive(self, mid: str, archived: bool = True) -> None:
        """Archived meetings keep everything but leave search, questions, action lists and the calendar."""
        if self.repo.get(mid) is None:
            raise KeyError(mid)
        self.repo.update(mid, archived=int(archived), archived_at=utc_iso(datetime.now(UTC)) if archived else None)
        self.touched(mid)
        self.m.changed()
        self.notify("meeting_updated", {"id": mid, "status": "READY", "archived": archived})

    def mark_parked(self, mid: str, indexes: list[int]) -> None:
        m = self.repo.get(mid)
        if m is None or not m.get("summary"):
            return
        for i in indexes:
            m["summary"]["action_items"][i]["parked"] = True
        self.repo.update(mid, summary_json=json.dumps(m["summary"]))
        self.touched(mid)

    def export(self, mid: str, fmt: str) -> tuple[str, str, str]:
        if fmt not in FORMATS:
            raise ValueError(f"unknown format {fmt}")
        m = self.repo.get(mid)
        if m is None:
            raise KeyError(mid)
        if fmt == "ai":  # transcript + the prompt, for another AI agent to summarise
            name = filename(m, "md").removesuffix(".md") + "_for_AI.md"
            return handoff_md(m, self.repo.segments(mid), self.vocabulary()), FORMATS[fmt], name
        return render(m, self.repo.segments(mid), fmt, self.vocabulary()), FORMATS[fmt], filename(m, fmt)

    def delete(self, mid: str) -> bool:
        m = self.repo.get(mid)
        if m is None or any(r.mid == mid for r in self._rec.values()):
            return False
        self.repo.delete(mid)
        with self._lock:
            if mid in self._sq:
                self._sq.remove(mid)
        try:
            Path(m["audio_path"]).unlink(missing_ok=True)
        except OSError:
            log.warning("could not delete %s", m["audio_path"])
        vault = self.vault()
        if vault is not None:  # its note stays in the vault (it may hold the user's own notes); the index drops it
            try:
                with self._vault_lock:
                    vault.write_overview(self.repo.all_with_summaries(), datetime.now(self.m.tz))
            except Exception as e:
                errors.report(self.m.db, "meetings", "Writing the Obsidian index failed", str(e), e)
        self.notify("meeting_updated", {"id": mid, "status": "DELETED"})
        return True

    def status(self) -> dict[str, Any]:
        return {"stt": self.stt.status, "busy": self._busy, "busy_kind": self._busy_kind, "queued": self._q.qsize(),
                "summaries_queued": len(self._sq), "summary_mode": self.summary_mode(),
                "summary_progress": {k: {"part": v[0], "parts": v[1]} for k, v in self._sum_progress.items()},
                "recording": [{"id": r.mid, "recorded_s": round(r.bytes / (SR * 2), 1)} for r in self._rec.values()]}
