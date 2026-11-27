"""Neural voiceprints for speaker detection (ADR-038): front-ends, model download, clustering on the cosine
distance, the service using them, and the one-time upgrade of meetings transcribed with the old MFCC features."""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import numpy as np
import pytest
from service.meetings import diarize, voice_embed
from service.meetings.service import MeetingService, wav_header
from service.meetings.voice_embed import SpeakerModel, VoiceEmbedder

from tests.support.fake_voiceprints import ToneVoiceprints, tone_meeting
from tests.support.meeting_audio import (
    ScriptedSegmentsSTT,
    piper_available,
    synth_meeting,
)

MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "speaker"


# ---- front-ends -------------------------------------------------------------------------------------------
def test_kaldi_fbank_matches_torchaudio() -> None:
    n = np.arange(16000)
    x = (0.3 * np.sin(2 * np.pi * 220 * n / 16000) + 0.1 * np.sin(2 * np.pi * 1500 * n / 16000)
         + 0.02 * np.cos(2 * np.pi * 3700 * n / 16000)).astype(np.float32)
    f = voice_embed.kaldi_fbank(x, 32768.0)
    # torchaudio.compliance.kaldi.fbank(x * 32768, num_mel_bins=80, dither=0, window_type="povey") - its mean
    assert f.shape == (98, 80)
    assert f[50, :4] == pytest.approx([1.248, 1.38, -0.057, -0.031], abs=2e-3)
    assert float(np.abs(f).mean()) == pytest.approx(0.1158, abs=1e-3)


def test_nemo_mel_is_normalised_per_feature() -> None:
    x = np.random.default_rng(0).normal(0, 0.1, 32000).astype(np.float32)
    f = voice_embed.nemo_mel(x)
    assert f.shape == (80, 201)  # centred frames: 1 + 32000 // 160
    assert np.abs(f.mean(axis=1)).max() < 1e-4
    assert np.abs(f.std(axis=1, ddof=1) - 1).max() < 1e-3


# ---- model download ---------------------------------------------------------------------------------------
def _model(body: bytes, sha: str | None = None) -> SpeakerModel:
    return SpeakerModel("tiny.onnx", "https://example.test/tiny.onnx", sha or hashlib.sha256(body).hexdigest(),
                        len(body), 4, "kaldi")


def _client(body: bytes):  # type: ignore[no-untyped-def]
    return lambda: httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=body)))


def test_model_is_downloaded_once_and_checked(tmp_path) -> None:  # type: ignore[no-untyped-def]
    body = b"onnx-bytes" * 100
    e = VoiceEmbedder(_model(body), tmp_path, client=_client(body))
    assert not e.available()
    assert e.fetch() and e.available()
    assert (tmp_path / "tiny.onnx").read_bytes() == body
    assert not list(tmp_path.glob("*.part"))


def test_a_tampered_download_is_thrown_away(tmp_path) -> None:  # type: ignore[no-untyped-def]
    body = b"onnx-bytes" * 100
    e = VoiceEmbedder(_model(body, sha="0" * 64), tmp_path, client=_client(body))
    assert not e.fetch()
    assert not e.available() and not list(tmp_path.iterdir())


# ---- clustering on the cosine distance ----------------------------------------------------------------------
def _voices(n_people: int, lines: int, spread: float, seed: int = 0):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(n_people, 192))
    truth = [i % n_people for i in range(lines)]
    feats = [centers[t] / np.linalg.norm(centers[t]) + rng.normal(0, spread, 192) for t in truth]
    return feats, truth


@pytest.mark.parametrize("people", [1, 2, 4])
def test_neural_voiceprints_count_the_people(people: int) -> None:
    feats, truth = _voices(people, 40, spread=0.05)
    d = diarize.diarize(feats, [3.0] * len(feats))
    assert max(d.labels) + 1 == people
    assert len({(a, b) for a, b in zip(d.labels, truth, strict=True)}) == people  # one label per person
    assert len(d.centroids_raw[0]) == 192


def test_forcing_the_count_and_profiles_of_the_other_kind_are_ignored() -> None:
    feats, _ = _voices(2, 20, spread=0.05)
    d = diarize.diarize(feats, [3.0] * 20, num_speakers=3)
    assert max(d.labels) + 1 == 3
    d = diarize.diarize(feats, [3.0] * 20)
    old = {"id": "v1", "name": "Old", "embedding": [0.0] * diarize.FEATURE_DIM}
    ana = {"id": "v2", "name": "Ana", "embedding": list(d.centroids_raw[1])}
    assert diarize.match_profiles(d, [old, ana]) == {1: ana}


# ---- the service ------------------------------------------------------------------------------------------
def _wav(path: Path, pcm: bytes) -> Path:
    path.write_bytes(wav_header(len(pcm)) + pcm)
    return path


def _svc(manager, tmp_path: Path, segs, voiceprints=None) -> MeetingService:  # type: ignore[no-untyped-def]
    return MeetingService(manager, tmp_path, "small.en", lambda k, p: None, stt=ScriptedSegmentsSTT(segs),  # type: ignore[arg-type]
                          voiceprints=voiceprints)  # type: ignore[arg-type]


def test_meetings_use_the_speaker_model(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    pcm, segs = tone_meeting([200, 200, 500, 200, 500, 500])
    vp = ToneVoiceprints()
    svc = _svc(manager, tmp_path, segs, vp)
    mid = svc.import_audio(_wav(tmp_path / "a.wav", pcm), "Sync")
    assert svc.wait_idle(30)
    lines = svc.repo.segments(mid, with_embeddings=True)
    assert [s["speaker_key"] for s in lines] == ["S1", "S1", "S2", "S1", "S2", "S2"]
    assert all(len(s["embedding"]) == ToneVoiceprints.dim for s in lines)


def test_old_meetings_and_remembered_voices_are_upgraded(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    pcm, segs = tone_meeting([200, 200, 500, 200, 500, 500])
    old = _svc(manager, tmp_path, segs)  # transcribed before the speaker model existed: MFCC voiceprints
    mid = old.import_audio(_wav(tmp_path / "a.wav", pcm), "Monday")
    assert old.wait_idle(30)
    first = old.repo.segments(mid)[0]["speaker_key"]
    old.rename_speaker(mid, first, "Ana", remember=True)
    assert len(old.repo.profiles(with_embeddings=True)[0]["embedding"]) == diarize.FEATURE_DIM
    keys = [s["speaker_key"] for s in old.repo.segments(mid)]

    new = _svc(manager, tmp_path, segs, ToneVoiceprints())
    new.upgrade_voiceprints()
    assert new.wait_idle(30)
    assert [s["speaker_key"] for s in new.repo.segments(mid)] == keys  # the user's speakers are kept
    assert all(len(s["embedding"]) == ToneVoiceprints.dim for s in new.repo.segments(mid, with_embeddings=True))
    assert len(new.repo.profiles(with_embeddings=True)[0]["embedding"]) == ToneVoiceprints.dim
    assert new.reembed_all() == 0  # done once

    pcm2, segs2 = tone_meeting([500, 200, 200, 500], seed=1)  # Tuesday: the other person speaks first
    new.stt = ScriptedSegmentsSTT(segs2)  # type: ignore[assignment]
    mid2 = new.import_audio(_wav(tmp_path / "b.wav", pcm2), "Tuesday")
    assert new.wait_idle(30)
    names = {s["key"]: (s["name"], s["auto"]) for s in new.repo.speakers(mid2)}
    assert names["S2"] == ("Ana", True)


def test_a_broken_model_falls_back_to_mfcc(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    class Broken(ToneVoiceprints):
        def embed(self, audio):  # type: ignore[no-untyped-def]
            raise RuntimeError("bad model file")

    pcm, segs = tone_meeting([200, 500])
    svc = _svc(manager, tmp_path, segs, Broken())
    mid = svc.import_audio(_wav(tmp_path / "a.wav", pcm), "Sync")
    assert svc.wait_idle(30)
    m = svc.repo.get(mid)
    assert m is not None and m["status"] == "READY"
    assert svc.voiceprints is None


# ---- the real model (when it is on this PC) ---------------------------------------------------------------
JENNY, RYAN, HFC = "en_GB-jenny_dioco-medium", "en_US-ryan-medium", "en_US-hfc_female-medium"


@pytest.mark.skipif(not piper_available(JENNY, RYAN, HFC) or
                    not (MODEL_DIR / voice_embed.MODELS[voice_embed.DEFAULT].file).exists(),
                    reason="Piper voices or the speaker model not on this PC")
@pytest.mark.parametrize("voices", [[JENNY], [JENNY, RYAN], [JENNY, RYAN, HFC]])
def test_real_speaker_model_tells_piper_voices_apart(voices) -> None:  # type: ignore[no-untyped-def]
    e = VoiceEmbedder(voice_embed.MODELS[voice_embed.DEFAULT], MODEL_DIR)
    pcm, truth = synth_meeting(voices, seed=len(voices))
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    feats = [e.embed(audio[int(a * 16000):int(b * 16000)]) for a, b, _, _ in truth]
    d = diarize.diarize(feats, [b - a for a, b, _, _ in truth])
    assert max(d.labels) + 1 == len(voices)
    pairs = {(lab, t[3]) for lab, t in zip(d.labels, truth, strict=True)}
    assert len(pairs) == len(voices)  # every line of a voice got the same speaker
