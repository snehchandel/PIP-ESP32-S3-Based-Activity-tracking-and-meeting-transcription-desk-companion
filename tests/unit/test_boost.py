"""Phrase boosting for Parakeet (ADR-040): the piece tree, the bonus decision, the boosted greedy TDT loop, and the
engine's GPU -> CPU fallback. Made-up words only (the repository is public)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from service.speech import boost
from service.speech.boost import BoostTree, boosted_decoding
from service.speech.parakeet import ParakeetSTT

VOCAB = {0: " Zor", 1: "vane", 2: " the", 3: " plan", 4: " Z", 5: "or", 6: " is", 7: "<blk>", 8: " Quill", 9: "mark",
         10: " ready", 11: "<unk>"}
BLANK = 7


def test_phrases_become_piece_paths() -> None:
    tree = BoostTree(["Zorvane", "quillmark"], VOCAB)
    assert tree.phrases == 2
    assert set(tree.root.children) == {0, 8}  # " Zor"+"vane" (fewest pieces = greedy), " Quill"+"mark" (capitalised)
    assert 1 in tree.root.children[0].children  # " Zor" -> "vane"
    assert 11 not in tree.root.children  # special tokens are never pieces


def test_bonus_is_small_to_start_and_large_to_continue() -> None:
    tree = BoostTree(["Zorvane"], VOCAB, first=1.0, nxt=3.0)
    logits = np.zeros(12)
    logits[2], logits[0] = 5.0, 3.5  # the model prefers " the"; " Zor" is 1.5 behind
    assert tree.pick(logits, (tree.root,)) == 2  # a first piece needs to be within 1.0
    logits[0] = 4.2
    assert tree.pick(logits, (tree.root,)) == 0
    started = tree.advance((tree.root,), 0)
    logits = np.zeros(12)
    logits[BLANK], logits[1] = 4.0, 1.5  # "vane" 2.5 behind blank: continued because a phrase is under way
    assert tree.pick(logits, started) == 1
    assert tree.advance(started, 1) == (tree.root,)  # phrase complete


class _FakeTdt:
    """Frame-by-frame logits for onnx-asr's greedy TDT loop (no ONNX)."""
    _blank_idx = BLANK
    _max_tokens_per_step = 10

    def __init__(self, frames: list[np.ndarray]) -> None:
        self.frames = frames
        self.pip_boost: BoostTree | None = None

    def _create_state(self) -> None:
        return None

    def _decode(self, tokens: list[int], state: Any, enc: np.ndarray) -> tuple[np.ndarray, int, None]:
        return self.frames[int(enc[0])][len(tokens)], 1, None

    def _decoding(self, out: np.ndarray, lens: np.ndarray, **kw: Any):  # type: ignore[no-untyped-def]
        for _, n in zip(out, lens, strict=True):  # plain greedy, one token per frame
            toks, times = [], []
            for t in range(int(n)):
                tok = int(self._decode(toks, None, out[0][t])[0].argmax())
                if tok != BLANK:
                    toks.append(tok)
                    times.append(t)
            yield toks, times, None


def _logits(**scores: float) -> np.ndarray:
    v = np.full(12, -5.0)
    for k, s in scores.items():
        v[int(k[1:])] = s
    return v


def test_boosted_loop_spells_the_phrase_and_keeps_durations() -> None:
    # frame t, tokens so far -> logits: the model hears " Z", "or", then hesitates between "vane" and blank
    table = {0: _logits(t4=3.0, t0=2.5), 1: _logits(t5=3.0, t1=2.0, t7=2.2), 2: _logits(t7=4.0, t1=1.8)}
    frames = [np.stack([table[t]] * 4) for t in range(3)]
    asr = _FakeTdt(frames)
    enc = np.arange(3, dtype=np.float32)[None, :, None]
    plain = next(boosted_decoding(asr, enc, np.array([3])))[0]
    assert [VOCAB[i] for i in plain] == [" Z", "or"]  # no tree: onnx-asr's own loop, "vane" lost
    boost.install(asr)
    asr.pip_boost = BoostTree(["Zorvane"], VOCAB, first=1.0, nxt=3.0)
    toks, times, _ = next(asr._decoding(enc, np.array([3])))
    assert "".join(VOCAB[i] for i in toks) == " Zorvane"
    assert times == sorted(times)


def test_a_gpu_failure_reloads_parakeet_on_the_cpu(tmp_path) -> None:  # type: ignore[no-untyped-def]
    loads: list[bool] = []

    class Model:
        def __init__(self, gpu: bool) -> None:
            self.gpu = gpu
            self.asr = type("A", (), {"_vocab": VOCAB, "pip_boost": None})()

        def recognize(self, chunks: list[Any], sample_rate: int) -> list[str]:
            if self.gpu:
                raise RuntimeError("CUDA out of memory")
            return ["ok"] * len(chunks)

    p = ParakeetSTT(Path(tmp_path), fallback=lambda: None)

    def load() -> Model:
        loads.append(p.allow_gpu)
        p.on_gpu = p.allow_gpu
        return Model(p.allow_gpu)

    p._load = load  # type: ignore[method-assign]
    p._model = load()
    p.vocabulary = ["Zorvane"]
    p._set_boost()
    assert p._recognize([np.zeros(16000)]) == ["ok"]
    assert loads == [True, False] and p.device == "cpu"
    assert isinstance(p._model.asr.pip_boost, BoostTree)  # boosting survives the reload
    p.unload()
    assert p.allow_gpu  # the next meeting tries the GPU again


# ---- the real model (when it is on this PC) -----------------------------------------------------------------
MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "parakeet-tdt-0.6b-v3"
VOICES = ["en_GB-jenny_dioco-medium", "en_US-ryan-medium", "en_US-hfc_female-medium", "en_US-lessac-medium"]


def test_real_parakeet_spells_boosted_names() -> None:
    import pytest

    from tests.support.meeting_audio import piper_available, synth_meeting
    if not piper_available(*VOICES) or not ParakeetSTT(MODEL_DIR, fallback=lambda: None).installed():
        pytest.skip("Piper voices or the Parakeet model not on this PC")
    terms = ["Zorvane", "Quillmark", "Brontexa", "Velquist"]  # made up: the model has never heard them
    clips = []
    for vi, voice in enumerate(VOICES):
        pcm, truth = synth_meeting([voice], lines=[f"Please send the notes to {t} today." for t in terms], seed=vi)
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        clips += [(audio[int(a * 16000):int(b * 16000)], terms[i]) for i, (a, b, _, _) in enumerate(truth)]
    p = ParakeetSTT(MODEL_DIR, fallback=lambda: None)
    assert p._ready()
    asr = p._model.asr

    def spelled() -> int:
        out = [r.text for r in p._model.recognize([c for c, _ in clips], sample_rate=16000)]
        return sum(term in text for (_, term), text in zip(clips, out, strict=True))

    plain = spelled()
    asr.pip_boost = BoostTree(terms, asr._vocab)
    boosted = spelled()
    assert boosted >= max(plain, 12)  # measured: 11 -> 15 of 16
    p.unload()
