"""Phrase boosting for Parakeet: the user's vocabulary steers recognition, as Whisper's hotwords did (ADR-040).

The idea of NVIDIA NeMo's GPU phrase boosting (a "boosting tree" in shallow fusion), for greedy TDT decoding:
the phrases become a tree of the model's word pieces; while decoding, a piece that starts a phrase, or continues one
that is under way, gets a bonus on top of the model's log-probability (larger once a phrase has started - NeMo's
depth scaling). The bonus only decides between pieces the model already finds nearly as likely, so ordinary speech
is left alone; the weight was tuned so general meeting audio does not get worse.

The model's SentencePiece file is not shipped with the ONNX export, so each phrase is entered in the two likely
spellings in pieces (fewest pieces, greedy longest match), as written and with a capital first letter.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np

FIRST = 0.5          # bonus (log-probability) for the first piece of a phrase: small - short common first pieces
                     # (" C", " An") otherwise start phrases that were never said
NEXT = 5.0           # bonus for every later piece of a phrase under way (the model already started it)
MAX_PHRASES = 200


@dataclass
class _Node:
    depth: int = 0
    children: dict[int, _Node] = field(default_factory=dict)


def _segmentations(text: str, pieces: dict[str, int]) -> list[list[int]]:
    """Two splits of `text` (leading space = word start) into vocabulary pieces: fewest pieces, greedy longest."""
    n = len(text)
    best: list[list[int] | None] = [None] * (n + 1)
    best[0] = []
    for i in range(n):
        if best[i] is None:
            continue
        for j in range(i + 1, min(n, i + 24) + 1):
            tid = pieces.get(text[i:j])
            if tid is not None and (best[j] is None or len(best[j]) > len(best[i]) + 1):  # type: ignore[arg-type]
                best[j] = best[i] + [tid]  # type: ignore[operator]
    out = [best[n]] if best[n] else []
    greedy: list[int] = []
    i = 0
    while i < n:
        for j in range(min(n, i + 24), i, -1):
            if text[i:j] in pieces:
                greedy.append(pieces[text[i:j]])
                i = j
                break
        else:
            greedy = []
            break
    if greedy and greedy not in out:
        out.append(greedy)
    return out  # type: ignore[return-value]


def _spellings(phrase: str) -> set[str]:
    words = phrase.split()
    if not words:
        return set()
    forms = {" ".join(words)}
    if words[0][:1].islower():
        forms.add(" ".join([words[0][:1].upper() + words[0][1:], *words[1:]]))
    return {" " + f for f in forms}


class BoostTree:
    """Word-piece tree of the phrases to boost, for one model vocabulary (id -> piece, word start = leading space)."""

    def __init__(self, phrases: Iterable[str], vocab: dict[int, str], first: float = FIRST, nxt: float = NEXT) -> None:
        pieces = {tok: tid for tid, tok in vocab.items() if tok and not (tok.startswith("<") and tok.endswith(">"))}
        self.first, self.next = first, nxt
        self.root = _Node()
        self.phrases = 0
        for phrase in list(dict.fromkeys(p.strip() for p in phrases if p and p.strip()))[:MAX_PHRASES]:
            added = False
            for text in _spellings(phrase):
                for seg in _segmentations(text, pieces):
                    node = self.root
                    for tid in seg:
                        node = node.children.setdefault(tid, _Node(node.depth + 1))
                    added = True
            self.phrases += int(added)

    def bonus(self, active: tuple[_Node, ...]) -> dict[int, float]:
        out: dict[int, float] = {}
        for node in active:
            b = self.next if node.depth else self.first
            for tid in node.children:
                if b > out.get(tid, 0.0):
                    out[tid] = b
        return out

    def pick(self, logits: np.ndarray, active: tuple[_Node, ...]) -> int:
        """argmax(log_softmax(logits) + bonus) without the softmax: the normaliser is the same for every token."""
        best = int(logits.argmax())
        top = float(logits[best])
        for tid, b in self.bonus(active).items():
            if logits[tid] + b > top:
                best, top = tid, float(logits[tid]) + b
        return best

    def advance(self, active: tuple[_Node, ...], token: int) -> tuple[_Node, ...]:
        """The phrases still under way after `token` (the root always: a phrase may start at any piece)."""
        nxt = [n.children[token] for n in active if token in n.children]
        return (self.root, *(n for n in nxt if n.children))


def boosted_decoding(asr: Any, encoder_out: np.ndarray, encoder_out_lens: np.ndarray,
                     **kwargs: object) -> Iterator[tuple[list[int], list[int], list[float] | None]]:
    """onnx-asr 0.12's greedy transducer loop (`_AsrWithTransducerDecoding._decoding`) with the boosting bonus
    added to the token scores. Durations (TDT) and timestamps are unchanged."""
    tree: BoostTree | None = getattr(asr, "pip_boost", None)
    if tree is None or not tree.root.children:
        yield from type(asr)._decoding(asr, encoder_out, encoder_out_lens, **kwargs)
        return
    need_logprobs = bool(kwargs.get("need_logprobs"))
    blank = asr._blank_idx
    for encodings, encodings_len in zip(encoder_out, encoder_out_lens, strict=True):
        prev_state = asr._create_state()
        tokens: list[int] = []
        timestamps: list[int] = []
        logprobs: list[float] = []
        active: tuple[_Node, ...] = (tree.root,)
        t = emitted = 0
        while t < encodings_len:
            logits, step, state = asr._decode(tokens, prev_state, encodings[t])
            token = tree.pick(logits, active)
            if token != blank:
                prev_state = state
                tokens.append(token)
                timestamps.append(t)
                emitted += 1
                active = tree.advance(active, token)
                if need_logprobs:
                    m = float(logits.max())
                    logprobs.append(float(logits[token]) - m - float(np.log(np.exp(logits - m).sum())))
            if step > 0:
                t += step
                emitted = 0
            elif token == blank or emitted == asr._max_tokens_per_step:
                t += 1
                emitted = 0
        yield tokens, timestamps, logprobs if need_logprobs else None


def install(asr: Any) -> None:
    """Route an onnx-asr transducer model's decoding through boosted_decoding (no tree = unchanged decoding)."""
    asr.pip_boost = None
    asr._decoding = lambda out, lens, **kw: boosted_decoding(asr, out, lens, **kw)
