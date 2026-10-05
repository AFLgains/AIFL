"""Ratings on the Elo scale.

  fit_ratings    Bradley-Terry over every match (draws half each way), anchors pinned to average 1500. Order-independent:
                 a new bot with a winning record against strong opponents rates above them straight away.
  fit_one        one bot against opponents of KNOWN rating (theirs held fixed): how `afl rate` places a new bot.
  elo_gap        the Elo difference a score implies (0.75 -> +191).

Ladders only ever combine matches of one engine version and one game length (the store keys everything by both).
"""
from __future__ import annotations

import math

import numpy as np


def elo_gap(score: float) -> float:
    score = min(max(score, 1e-3), 1 - 1e-3)
    return -400.0 * math.log10(1.0 / score - 1.0)


def expected(r_a: float, r_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((r_b - r_a) / 400.0))


def fit_ratings(matches, labels=None, anchors=None, iters=300, prior=2.0) -> dict:
    """matches: [{"a": label, "b": label, "score": 1 | 0.5 | 0 for a}]. A weak prior of `prior` games at 50 % against an
    average player keeps bots with few games sane. `anchors` (labels) average exactly 1500; by default every "zoo:" bot."""
    labels = sorted({m["a"] for m in matches} | {m["b"] for m in matches}) if labels is None else list(labels)
    n = len(labels)
    if n == 0:
        return {}
    idx = {lb: i for i, lb in enumerate(labels)}
    wins = np.zeros((n, n))                                                 # wins[i, j] = wins of i over j (draws half)
    for m in matches:
        i = idx.get(m["a"]); j = idx.get(m["b"])
        if i is None or j is None:
            continue
        wins[i, j] += m["score"]; wins[j, i] += 1.0 - m["score"]
    games = wins + wins.T
    np.fill_diagonal(games, 0.0)
    w = wins.sum(1) + prior * 0.5
    s = np.ones(n)
    for _ in range(iters):                                                  # MM algorithm (Hunter 2004); the prior is a virtual opponent of strength 1
        denom = prior / (s + 1.0) + (games / (s[:, None] + s[None, :])).sum(1)
        new = np.where(denom > 0, w / np.where(denom > 0, denom, 1.0), s)
        s = new / math.exp(np.log(new).mean())                             # renormalise: geometric mean 1
    raw = 400.0 * np.log10(s)
    anchors = [lb for lb in labels if lb.startswith("zoo:")] if anchors is None else [lb for lb in anchors if lb in idx]
    offset = float(np.mean([raw[idx[lb]] for lb in anchors])) if anchors else 0.0
    return {lb: float(1500.0 + raw[idx[lb]] - offset) for lb in labels}


def fit_one(results, ratings: dict) -> float:
    """Maximum-likelihood rating of one bot from [(opponent_label, score)] against opponents of known rating."""
    grid = np.arange(0.0, 3200.0, 1.0)
    ll = np.zeros_like(grid)
    for opp, s in results:
        p = np.clip(1.0 / (1.0 + 10 ** ((ratings[opp] - grid) / 400.0)), 1e-9, 1 - 1e-9)
        ll += s * np.log(p) + (1 - s) * np.log(1 - p)
    return float(grid[int(np.argmax(ll))])


def bootstrap_one(results, ratings, n=1000, seed=0):
    """95 % interval for fit_one by resampling the games."""
    rng = np.random.default_rng(seed)
    boots = [fit_one([results[i] for i in rng.integers(0, len(results), len(results))], ratings) for _ in range(n)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(lo), float(hi)


def score_summary(outcomes) -> dict:
    """W-L-D, score and a +/- 2 s.e. band for a list of outcomes (1 / 0.5 / 0)."""
    o = list(outcomes); n = len(o)
    w = sum(1 for x in o if x == 1.0); d = sum(1 for x in o if x == 0.5); l = n - w - d
    score = (w + 0.5 * d) / n if n else float("nan")
    se = math.sqrt(max(score * (1 - score), 1e-6) / n) if n else float("nan")
    return {"n": n, "w": w, "l": l, "d": d, "score": score, "se": se, "elo": elo_gap(score) + 0.0 if n else float("nan"),
            "elo_lo": elo_gap(max(score - 2 * se, 0.001)) if n else float("nan"), "elo_hi": elo_gap(min(score + 2 * se, 0.999)) if n else float("nan")}
