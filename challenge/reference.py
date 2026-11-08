"""Build the reference pool of the challenge: the fixed ratings that grade.py rates a bot against.

    python challenge/reference.py                  # AFL8:  round_29a + the 17 zoo bots
    python challenge/reference.py --game afl18     # AFL18: the 12 zoo bots

Every pair of pool bots plays SEEDS seeds from both ends (a full round robin). A Bradley-Terry fit (the model behind
Elo) gives each bot a rating; the game's five anchor bots average exactly 1500. The result goes to
challenge/<game>/reference.json, with the hash of each bot's code: grade.py refuses to use a pool whose code changed.

Run this again only when the engine version changes. A new pool changes every rating on the challenge scale.
"""
from __future__ import annotations

import argparse
import datetime
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import grade                                                                          # noqa: E402
from aflsim.games import engine_version, get_game                                    # noqa: E402
from aflsim.match.ladder import rating_errors                                        # noqa: E402
from aflsim.match.rating import fit_ratings                                          # noqa: E402

SEEDS = 20                       # per pair, x2 ends = 40 games
SEED0 = 900_000                  # far from the self-test seeds (1 to 200)


def pool(game):
    g = get_game(game)
    bots = {"zoo:" + z: "zoo:" + z for z in sorted(g.ZOO)}
    if game == "afl8":
        bots = {"round_29a": "challenge/afl8/round_29a.py", **bots}
    return bots


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the challenge's reference pool ratings.")
    ap.add_argument("--game", default="afl8", choices=sorted(grade.TARGETS))
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--parallel", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args(argv)
    game = a.game; g = get_game(game); bots = pool(game)

    jobs = []
    for x, y in itertools.combinations(sorted(bots), 2):          # x is "the challenger" only for bookkeeping
        jobs += grade.jobs_against(game, grade.resolve(bots[x]), x, grade.resolve(bots[y]), SEED0, a.seeds)
        jobs[-2 * a.seeds:] = [(gm, c, ol, o, s, side) + (x,) for gm, c, ol, o, s, side in jobs[-2 * a.seeds:]]
    print("%s: %d bots, %d pairs, %d games" % (game, len(bots), len(bots) * (len(bots) - 1) // 2, len(jobs)))
    rows = grade.run(_play, jobs, a.parallel, "round robin")

    matches = [{"a": r["me"], "b": r["opp"], "score": r["score"]} for r in rows]
    anchors = ["zoo:" + z for z in g.ANCHORS]
    ratings = fit_ratings(matches, labels=sorted(bots), anchors=anchors)
    se = rating_errors(matches, ratings)
    errors = sum(r["errors"] for r in rows)
    out = {"game": game, "engine_version": engine_version(g), "seconds": grade.SECONDS, "seeds_per_pair": a.seeds,
           "both_ends": True, "seed0": SEED0, "games": len(rows), "anchors": anchors, "anchor_mean": 1500,
           "built": datetime.date.today().isoformat(), "errors": errors,
           "bots": {lb: {"spec": bots[lb], "hash": grade.code_hash(grade.resolve(bots[lb]), game), "rating": round(ratings[lb], 1), "se": round(se[lb], 1)}
                    for lb in sorted(bots, key=lambda b: -ratings[b])}}
    path = grade.reference_path(game)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    for lb, b in out["bots"].items():
        print("  %-16s %6.0f  +- %.0f" % (lb, b["rating"], b["se"]))
    print("errors in all games: %d" % errors)
    print("wrote %s" % path)


def _play(job):
    """grade.play with the 'challenger' label carried through (both bots are pool bots here)."""
    *base, me = job
    row = grade.play(tuple(base))
    row["me"] = me
    return row


if __name__ == "__main__":
    main()
