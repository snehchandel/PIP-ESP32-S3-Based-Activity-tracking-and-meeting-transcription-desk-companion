"""Who spoke when: voice features per transcript segment, clustering into speakers, remembered voices.

Runs on the laptop CPU with numpy only (no model download, nothing leaves the PC):
  * features: MFCC statistics (spectral envelope = vocal tract) + pitch statistics per segment;
  * clustering: average-linkage agglomerative clustering on the RMS distance of features scaled by their typical
    within-speaker spread. The speaker count is found automatically (merging stops at a fixed distance) or
    forced by the user;
  * remembered voices: when the user names a speaker, the raw feature centroid is stored as a profile and
    later meetings label matching clusters with that name automatically.

It is a lightweight method: distinct voices (e.g. different genders/ages) separate well, similar voices may be
merged - which is why the app lets the user re-run detection with a fixed speaker count, move single lines to
another speaker, merge speakers and rename them."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any

import numpy as np

SR = 16000
N_MFCC = 20
MIN_FEATURE_S = 0.8        # shorter segments get the speaker of their neighbours / nearest voice
MERGE_DISTANCE = 1.75      # average (scaled RMS) distance at which two groups count as different people
PROFILE_DISTANCE = 1.45    # a speaker this close to a remembered voice is labelled with its name
TINY_SPEAKER_S = 8.0       # a detected "speaker" needs this much talk time...
MIN_SPEAKER_LINES, MIN_SPEAKER_S = 2, 3.0  # ...or 2+ lines and 3 s; smaller groups join the nearest voice
MAX_CLUSTER_ITEMS = 1500   # longer meetings cluster a sample, the rest is assigned to the nearest voice

# Typical within-speaker spread of each feature (MFCC means 1-19, MFCC stds, delta stds, log-F0 median, log-F0
# IQR), measured on multi-voice recordings. Dividing by it weights every feature by how much it varies *between*
# people relative to how much one person varies, so a fixed merge distance works for any meeting. The floor of
# 0.1 keeps the high-order cepstra (which mostly track background noise) from dominating.
WITHIN_SCALE = np.maximum(0.10, np.array([
    1.338, 0.643, 1.071, 0.576, 0.467, 0.447, 0.264, 0.346, 0.296, 0.240, 0.217, 0.214, 0.200, 0.247, 0.198, 0.223,
    0.218, 0.199, 0.186, 1.098, 0.412, 0.294, 0.422, 0.242, 0.224, 0.185, 0.189, 0.112, 0.114, 0.132, 0.098, 0.142,
    0.165, 0.135, 0.142, 0.148, 0.154, 0.189, 0.572, 0.221, 0.147, 0.131, 0.108, 0.083, 0.099, 0.071, 0.082, 0.075,
    0.068, 0.071, 0.059, 0.060, 0.061, 0.056, 0.055, 0.070, 0.062, 0.070, 0.073]))
FEATURE_DIM = len(WITHIN_SCALE)


def _mel(f: np.ndarray | float) -> np.ndarray | float:
    return 2595.0 * np.log10(1.0 + np.asarray(f) / 700.0)


def _imel(m: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


@cache
def _filterbank(n_mels: int = 40, nfft: int = 512, fmin: float = 60.0, fmax: float = 7600.0) -> np.ndarray:
    pts = _imel(np.linspace(float(_mel(fmin)), float(_mel(fmax)), n_mels + 2))
    bins = np.floor((nfft + 1) * pts / SR).astype(int)
    fb = np.zeros((n_mels, nfft // 2 + 1))
    for i in range(n_mels):
        lo, c, hi = bins[i], bins[i + 1], bins[i + 2]
        if c > lo:
            fb[i, lo:c] = (np.arange(lo, c) - lo) / (c - lo)
        if hi > c:
            fb[i, c:hi] = (hi - np.arange(c, hi)) / (hi - c)
    return fb


@cache
def _dct(n_out: int = N_MFCC, n_in: int = 40) -> np.ndarray:
    k = np.arange(n_out)[:, None]
    n = np.arange(n_in)[None, :]
    m = np.cos(np.pi * k * (2 * n + 1) / (2 * n_in)) * np.sqrt(2.0 / n_in)
    m[0] /= np.sqrt(2.0)
    return m


def _frames(x: np.ndarray, size: int, hop: int) -> np.ndarray:
    if len(x) < size:
        return np.zeros((0, size), dtype=np.float32)
    return np.lib.stride_tricks.sliding_window_view(x, size)[::hop]


def _pitch(x: np.ndarray, voiced_mask_energy: float) -> np.ndarray:
    """F0 (Hz) of voiced 40 ms frames by normalised autocorrelation (60-400 Hz)."""
    fr = _frames(x, 640, 320)
    if not len(fr):
        return np.zeros(0)
    e = (fr ** 2).mean(axis=1)
    fr = fr[e > voiced_mask_energy]
    if not len(fr):
        return np.zeros(0)
    fr = fr - fr.mean(axis=1, keepdims=True)
    spec = np.fft.rfft(fr * np.hanning(640), 1280)
    ac = np.fft.irfft(np.abs(spec) ** 2, 1280)[:, :640]
    ac = ac / np.maximum(ac[:, :1], 1e-9)
    lo, hi = SR // 400, SR // 60
    lag = lo + np.argmax(ac[:, lo:hi], axis=1)
    peak = ac[np.arange(len(ac)), lag]
    return (SR / lag[peak > 0.35]).astype(np.float64)


def voice_features(audio: np.ndarray) -> np.ndarray | None:
    """Raw feature vector of one stretch of speech (float32 mono 16 kHz), or None if too short/quiet."""
    if len(audio) < int(MIN_FEATURE_S * SR):
        return None
    x = np.append(audio[:1], audio[1:] - 0.97 * audio[:-1]).astype(np.float64)
    fr = _frames(x, 400, 160)
    spec = np.abs(np.fft.rfft(fr * np.hamming(400), 512)) ** 2
    mel = np.log(spec @ _filterbank().T + 1e-10)
    energy = mel.sum(axis=1)
    keep = energy >= np.percentile(energy, 35)  # speech frames, not the pauses between words
    if keep.sum() < 30:
        return None
    mfcc = (mel[keep] @ _dct().T)[:, 1:]  # drop c0 (loudness)
    delta = np.diff(mfcc, axis=0)
    raw = audio.astype(np.float64)
    f0 = _pitch(raw, float(np.percentile((_frames(raw, 640, 320) ** 2).mean(axis=1), 40)) if len(raw) >= 640 else 0.0)
    if len(f0) >= 5:
        lf = np.log(f0)
        pitch = np.array([np.median(lf), np.subtract(*np.percentile(lf, [75, 25]))])
    else:
        pitch = np.array([np.log(150.0), 0.2])  # unvoiced: neutral pitch
    return np.concatenate([mfcc.mean(axis=0), mfcc.std(axis=0), delta.std(axis=0), pitch])


def _scaled(raw: np.ndarray) -> np.ndarray:
    return np.asarray(raw, dtype=np.float64) / WITHIN_SCALE


def _rms_dist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise RMS distance between the rows of a and b (scaled features)."""
    d2 = (a ** 2).sum(1)[:, None] + (b ** 2).sum(1)[None, :] - 2.0 * a @ b.T
    return np.sqrt(np.maximum(d2, 0.0) / a.shape[1])


def _agglomerate(z: np.ndarray, k: int | None, max_k: int) -> np.ndarray:
    """Average-linkage clustering. Stops at k clusters, or (auto) when the closest pair of clusters is further
    apart than MERGE_DISTANCE - but never with more than max_k clusters. Returns a cluster id per row."""
    n = len(z)
    if n <= 1:
        return np.zeros(n, dtype=int)
    dist = _rms_dist(z, z)
    np.fill_diagonal(dist, np.inf)
    sizes = np.ones(n)
    labels = np.arange(n)
    clusters = n
    target = max(1, k) if k else 1
    while clusters > target:
        i, j = divmod(int(np.argmin(dist)), n)
        if k is None and dist[i, j] > MERGE_DISTANCE and clusters <= max_k:
            break
        si, sj = sizes[i], sizes[j]
        new = (dist[i] * si + dist[j] * sj) / (si + sj)  # Lance-Williams update for average linkage
        dist[i] = new
        dist[:, i] = new
        dist[i, i] = np.inf
        dist[j] = np.inf
        dist[:, j] = np.inf
        sizes[i] += sj
        labels[labels == j] = i
        clusters -= 1
    return labels


@dataclass
class Diarization:
    labels: list[int]                  # speaker index per segment (0-based, in order of first appearance)
    centroids_raw: list[list[float]]   # per speaker: duration-weighted mean raw features (remembered voices)
    samples: list[int]                 # per speaker: segments with usable features


def diarize(feats: list[np.ndarray | None], durations: list[float], num_speakers: int | None = None,
            max_speakers: int = 8) -> Diarization:
    n = len(feats)
    idx = [i for i, f in enumerate(feats) if f is not None and len(f) == FEATURE_DIM]
    if not idx:
        return Diarization([0] * n, [], [])
    raw = np.stack([np.asarray(feats[i]) for i in idx])
    z = _scaled(raw)
    dur = np.array([durations[i] for i in idx])
    # long meetings: cluster the longest segments, assign the rest to the nearest voice
    core = np.sort(np.argsort(-dur)[:MAX_CLUSTER_ITEMS])
    lab_core = _agglomerate(z[core], num_speakers, max_speakers)

    def centroids(groups: list[np.ndarray]) -> np.ndarray:
        return np.stack([(z[g] * dur[g, None]).sum(0) / max(dur[g].sum(), 1e-9) for g in groups])

    groups = [core[lab_core == g] for g in sorted(set(lab_core.tolist()))]
    if num_speakers is None and len(groups) > 1:  # absorb stray mini-clusters (a cough, a laugh, an odd line)
        talk = [float(dur[g].sum()) for g in groups]
        keep = [g for g, t in zip(groups, talk, strict=True)
                if t >= TINY_SPEAKER_S or (len(g) >= MIN_SPEAKER_LINES and t >= MIN_SPEAKER_S)]
        groups = keep or [groups[int(np.argmax(talk))]]
    lab = np.argmin(_rms_dist(z, centroids(groups)), axis=1)  # every featured segment -> nearest voice
    per_seg: list[int | None] = [None] * n
    for pos, i in enumerate(idx):
        per_seg[i] = int(lab[pos])
    # segments without usable features take the speaker of the one before (turns rarely change mid-mumble)
    last = per_seg[idx[0]]
    for i in range(n):
        if per_seg[i] is None:
            per_seg[i] = last
        last = per_seg[i]
    remap: dict[int, int] = {}  # number speakers in order of first appearance
    for v in per_seg:
        if v is not None and v not in remap:
            remap[v] = len(remap)
    labels = [remap[v] for v in per_seg if v is not None]
    cents, samples = [], []
    for old in sorted(remap, key=remap.__getitem__):
        rows = np.array([pos for pos, i in enumerate(idx) if per_seg[i] == old])
        w = dur[rows]
        cents.append(((raw[rows] * w[:, None]).sum(0) / max(w.sum(), 1e-9)).tolist())
        samples.append(len(rows))
    return Diarization(labels, cents, samples)


def match_profiles(d: Diarization, profiles: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """speaker index -> remembered voice, closest pairs first, each voice used at most once."""
    usable = [p for p in profiles if len(p["embedding"]) == FEATURE_DIM]
    if not d.centroids_raw or not usable:
        return {}
    dist = _rms_dist(_scaled(np.array(d.centroids_raw)), _scaled(np.array([p["embedding"] for p in usable])))
    out: dict[int, dict[str, Any]] = {}
    for flat in np.argsort(dist, axis=None):
        si, pi = divmod(int(flat), len(usable))
        if dist[si, pi] > PROFILE_DISTANCE:
            break
        if si in out or any(v["id"] == usable[pi]["id"] for v in out.values()):
            continue
        out[si] = usable[pi]
    return out
