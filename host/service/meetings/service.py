"""Meeting recorder + transcriber.

Recording: PIP streams its mic (AUDIO_START activity 4 = MEETING) for as long as the meeting runs. Every chunk
is appended to data/meetings/<id>.wav as it arrives, so nothing is held in memory and a crash loses nothing
already received; chunks lost to a link drop are filled with silence (the timeline stays true).

Transcription runs on this PC in a background thread with its own faster-whisper instance (voice commands
never wait behind a long meeting): 10-minute windows cut at quiet moments -> timed segments -> voice features
-> speakers (diarize.py) -> remembered voices name the speakers they recognise; the rest are "Speaker 01..."
until the user names them in the app."""
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
from ..speech.stt import SpeechToText
from ..state.manager import DeviceStateManager
from . import diarize
from .export import FORMATS, filename, render
from .store import MeetingRepo, speaker_label

log = logging.getLogger("pip.meetings")
SR = 16000
CHUNK_BYTES = 640               # one 20 ms device audio chunk
WINDOW_S = 600.0                # transcribe in 10 minute windows...
CUT_SEARCH_S = 30.0             # ...cut at the quietest moment of the window's last 30 s
STALE_RECORDING_S = 180.0       # no audio for this long: the device is gone, keep what we have
MAX_GAP_CHUNKS = 30000          # a seq jump larger than this (10 min) is a restart, not lost audio
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


class MeetingService:
    def __init__(self, manager: DeviceStateManager, data_dir: Path, model_name: str, notify: Notify,
                 summarizer: Callable[[], Any] | None = None, stt: SpeechToText | None = None) -> None:
        self.m = manager
        self.repo = MeetingRepo(manager.db)
        self.dir = data_dir / "meetings"
        self.stt = stt or SpeechToText(model_name)
        self.notify = notify
        self.summarizer = summarizer  # -> a planner with summarize_meeting(text, meta) (Kimi, budget-checked)
        self._rec: dict[int, _Recording] = {}
        self._q: queue.Queue[tuple[str, int | None]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._busy = ""
        self._lock = threading.RLock()

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
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="pip-meetings", daemon=True)
                self._worker.start()

    def wait_idle(self, timeout: float = 600.0) -> bool:
        """Tests: block until the queue is processed."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._q.unfinished_tasks == 0:
                return True
            time.sleep(0.05)
        return False

    def _run(self) -> None:
        while True:
            try:
                mid, n = self._q.get(timeout=30)
            except queue.Empty:
                self.stt.unload()  # give the memory back until the next meeting
                return
            try:
                self._busy = mid
                self.transcribe(mid, n)
            except Exception as e:
                errors.report(self.m.db, "meetings", "Meeting transcription failed", str(e), e, meeting=mid)
                self.repo.update(mid, status="FAILED", error=str(e)[:300])
                self.notify("meeting_updated", {"id": mid, "status": "FAILED"})
            finally:
                self._busy = ""
                self._q.task_done()

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

            for s0, s1, text in self.stt.transcribe_segments(audio, progress):
                feats = diarize.voice_features(audio[int(s0 * SR): int(s1 * SR)])
                segments.append({"start_s": round(pos + s0, 2), "end_s": round(pos + s1, 2), "text": text,
                                 "embedding": [round(float(x), 5) for x in feats] if feats is not None else None})
            pos = end
        self._assign_speakers(mid, segments, num_speakers)
        self.repo.update(mid, status="READY", progress=1.0, duration_s=round(total, 2))
        log.info("meeting %s transcribed: %d segments", mid, len(segments))
        self.notify("meeting_updated", {"id": mid, "status": "READY", "progress": 1.0})

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

    # ---- review ---------------------------------------------------------------------------------------------
    def speaker_centroid(self, mid: str, key: str) -> tuple[list[float], int] | None:
        rows = [s for s in self.repo.segments(mid, with_embeddings=True)
                if s["speaker_key"] == key and s["embedding"] and len(s["embedding"]) == diarize.FEATURE_DIM]
        if not rows:
            return None
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
        return {"key": key, "name": name, "profile_id": profile_id}

    def summarize(self, mid: str) -> dict[str, Any]:
        m = self.repo.get(mid)
        if m is None:
            raise KeyError(mid)
        if self.summarizer is None:
            raise RuntimeError("no AI configured")
        segs = self.repo.segments(mid)
        if not segs:
            raise ValueError("this meeting has no transcript yet")
        text = render({**m, "summary": None, "notes": ""}, segs, "txt")
        summary = self.summarizer().summarize_meeting(text[-120_000:])
        data = summary.model_dump() if hasattr(summary, "model_dump") else dict(summary)
        self.repo.update(mid, summary_json=json.dumps(data))
        if data.get("title") and m["title"].startswith("Meeting · "):
            self.repo.update(mid, title=str(data["title"])[:80])
        self.notify("meeting_updated", {"id": mid, "status": m["status"]})
        return data

    def export(self, mid: str, fmt: str) -> tuple[str, str, str]:
        if fmt not in FORMATS:
            raise ValueError(f"unknown format {fmt}")
        m = self.repo.get(mid)
        if m is None:
            raise KeyError(mid)
        return render(m, self.repo.segments(mid), fmt), FORMATS[fmt], filename(m, fmt)

    def delete(self, mid: str) -> bool:
        m = self.repo.get(mid)
        if m is None or any(r.mid == mid for r in self._rec.values()):
            return False
        self.repo.delete(mid)
        try:
            Path(m["audio_path"]).unlink(missing_ok=True)
        except OSError:
            log.warning("could not delete %s", m["audio_path"])
        self.notify("meeting_updated", {"id": mid, "status": "DELETED"})
        return True

    def status(self) -> dict[str, Any]:
        return {"stt": self.stt.status, "busy": self._busy, "queued": self._q.qsize(),
                "recording": [{"id": r.mid, "recorded_s": round(r.bytes / (SR * 2), 1)} for r in self._rec.values()]}
