"""NVIDIA Parakeet for meeting transcripts (ADR-039): sentence lines from token times, the pinned model download,
the Whisper fallback, a fine-tuned model folder, which model made a transcript, and the model's own words kept when
the user corrects a line (training/test data for a fine-tune)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from service.config import Settings
from service.main import create_app
from service.meetings.service import MeetingService, wav_header
from service.speech import parakeet
from service.speech.parakeet import ModelFile, ParakeetSTT, split_sentences

from tests.support.meeting_audio import (
    ScriptedSegmentsSTT,
    piper_available,
    synth_meeting,
)

MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / parakeet.NAME


# ---- lines from token times ---------------------------------------------------------------------------------
def test_sentences_become_lines_in_meeting_time() -> None:
    toks = [" Let", "'s", " start", ".", " Ok", ".", " I", "'ll", " send", " the", " deck", " Friday", "."]
    times = [0.0, 0.2, 0.4, 0.9, 1.2, 1.4, 2.0, 2.2, 2.5, 2.8, 3.0, 3.3, 3.8]
    lines = split_sentences(toks, times, start_s=100.0, end_s=104.5)
    # "Ok." alone is too short for a line (1.5 s): it stays with the sentence before
    assert [t for _, _, t in lines] == ["Let's start. Ok.", "I'll send the deck Friday."]
    assert lines[0][0] == 100.0 and lines[0][1] <= lines[1][0] == 102.0
    assert lines[1][1] == 104.5


# ---- the pinned download ------------------------------------------------------------------------------------
def _files(monkeypatch, bodies: dict[str, bytes], bad: str = "") -> None:  # type: ignore[no-untyped-def]
    files = tuple(ModelFile(n, len(b), "0" * 64 if n == bad else hashlib.sha256(b).hexdigest()) for n, b in bodies.items())
    monkeypatch.setattr(parakeet, "FILES", files)
    monkeypatch.setattr(parakeet, "_hf_cache_copy", lambda f: None)


def _serve(bodies: dict[str, bytes]):  # type: ignore[no-untyped-def]
    def handler(req: httpx.Request) -> httpx.Response:
        assert parakeet.REVISION in str(req.url)  # always the pinned revision
        return httpx.Response(200, content=bodies[req.url.path.rsplit("/", 1)[-1]])
    return lambda: httpx.Client(transport=httpx.MockTransport(handler))


def test_model_files_are_downloaded_and_checked(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    bodies = {"config.json": b"{}", "encoder-model.onnx": b"e" * 5000}
    _files(monkeypatch, bodies)
    p = ParakeetSTT(tmp_path, fallback=lambda: None, client=_serve(bodies))
    assert not p.installed()
    p.fetch()
    assert p.installed() and (tmp_path / "encoder-model.onnx").read_bytes() == bodies["encoder-model.onnx"]
    assert p.done_bytes == 5002 and not list(tmp_path.glob("*.part"))


def test_a_file_with_the_wrong_checksum_is_refused(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    bodies = {"config.json": b"{}", "encoder-model.onnx": b"e" * 5000}
    _files(monkeypatch, bodies, bad="encoder-model.onnx")
    p = ParakeetSTT(tmp_path, fallback=lambda: None, client=_serve(bodies))
    with pytest.raises(RuntimeError, match="checksum"):
        p.fetch()
    assert not (tmp_path / "encoder-model.onnx").exists() and not list(tmp_path.glob("*.part"))


# ---- fallback, fine-tuned folder, provenance ----------------------------------------------------------------
class _Whisper(ScriptedSegmentsSTT):
    model_name = "large-v3-turbo"


def _tone(path: Path, seconds: float = 6.0) -> Path:
    pcm = (np.random.default_rng(0).normal(0, 2000, int(16000 * seconds))).astype("<i2").tobytes()
    path.write_bytes(wav_header(len(pcm)) + pcm)
    return path


def _offline() -> httpx.Client:
    def fail(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")
    return httpx.Client(transport=httpx.MockTransport(fail))


def test_offline_first_use_falls_back_to_whisper(manager, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(parakeet, "_hf_cache_copy", lambda f: None)  # this PC's Hugging Face cache must not help
    whisper = _Whisper([(0.0, 2.0, "Hello there."), (2.5, 5.0, "Send the deck.")])
    p = ParakeetSTT(tmp_path / "pk", fallback=lambda: whisper, client=_offline)
    svc = MeetingService(manager, tmp_path, "unused", lambda k, d: None, stt=p)  # type: ignore[arg-type]
    mid = svc.import_audio(_tone(tmp_path / "a.wav"), "Sync")
    assert svc.wait_idle(30)
    m = svc.repo.get(mid)
    assert m is not None and m["status"] == "READY" and m["speech_model"] == "large-v3-turbo"
    assert [s["text"] for s in svc.repo.segments(mid)] == ["Hello there.", "Send the deck."]
    assert p.status.startswith("FALLBACK") and "offline" in p.status


def test_a_fine_tuned_folder_is_used_as_it_is(tmp_path) -> None:  # type: ignore[no-untyped-def]
    folder = tmp_path / "parakeet-ft-2027-01"
    folder.mkdir()
    p = ParakeetSTT(folder, fallback=lambda: None, client=_offline, custom=True)
    assert p.label == f"{parakeet.NAME}@parakeet-ft-2027-01"
    assert not p.installed()
    with pytest.raises(RuntimeError, match="incomplete"):
        p._load()  # never downloads the stock model over a fine-tuned folder
    assert not list(folder.iterdir())


def test_corrections_keep_what_the_model_heard(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = MeetingService(manager, tmp_path, "unused", lambda k, d: None,  # type: ignore[arg-type]
                         stt=ScriptedSegmentsSTT([(0.0, 2.0, "We meet with Anna on Friday.")]))
    mid = svc.import_audio(_tone(tmp_path / "a.wav"), "Sync")
    assert svc.wait_idle(30)
    seg = svc.repo.segments(mid)[0]["id"]
    for text in ("We meet with Ana on Friday.", "We meet with Ana on Friday!", "We meet with Ana on Friday!"):
        assert svc.repo.set_segment_text(mid, seg, text)
    row = manager.db.one("SELECT text, raw_text FROM meeting_segments WHERE id=?", (seg,))
    assert (row["text"], row["raw_text"]) == ("We meet with Ana on Friday!", "We meet with Anna on Friday.")


# ---- settings -----------------------------------------------------------------------------------------------
def test_parakeet_is_the_default_meeting_model_and_can_be_switched(tmp_path) -> None:  # type: ignore[no-untyped-def]
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    with TestClient(create_app(s)) as c:
        svcs = c.app.state.services  # type: ignore[attr-defined]
        m = c.get("/api/v1/settings/meetings").json()
        assert m["speech_model"] == "auto" and m["speech_model_active"] == parakeet.NAME
        assert isinstance(svcs.meetings.stt, ParakeetSTT)
        m = c.put("/api/v1/settings/meetings", json={"speech_model": "large-v3-turbo"}).json()
        assert m["speech_model_active"] == "large-v3-turbo"
        assert svcs.meetings.stt.model_name == "large-v3-turbo"
        m = c.put("/api/v1/settings/meetings", json={"speech_model": parakeet.NAME}).json()
        assert isinstance(svcs.meetings.stt, ParakeetSTT)


# ---- the real model (when it is on this PC) -----------------------------------------------------------------
JENNY, RYAN = "en_GB-jenny_dioco-medium", "en_US-ryan-medium"


@pytest.mark.skipif(not piper_available(JENNY, RYAN) or not ParakeetSTT(MODEL_DIR, fallback=lambda: None).installed(),
                    reason="Piper voices or the Parakeet model not on this PC")
def test_real_parakeet_transcribes_a_meeting() -> None:
    pcm, truth = synth_meeting([JENNY, RYAN], seed=2)
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    lines = ParakeetSTT(MODEL_DIR, fallback=lambda: None).transcribe_segments(audio)
    ref, hyp = _words(" ".join(t for *_, t, _ in truth)), _words(" ".join(t for *_, t in lines))
    assert _edits(ref, hyp) / len(ref) < 0.1  # word error rate
    assert all(b > a for a, b, _ in lines) and lines == sorted(lines)


def _words(text: str) -> list[str]:
    return "".join(ch for ch in text.lower() if ch.isalnum() or ch in " '").split()


def _edits(a: list[str], b: list[str]) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]
