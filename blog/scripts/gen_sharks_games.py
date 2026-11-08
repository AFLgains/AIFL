"""Two real games against the Sharks (round_36a) on the same seed: the original Power, and the Power with Claude's plan
with no limit. Each game is recorded for the replay, with the network's rating at every decision.

    python blog/scripts/gen_sharks_games.py [--search 30] [--seed N]

The seed is chosen from the official grading seeds (Power as team A) so that each result is typical of its 400-game
grade: the original Power loses by about its mean margin (-25), and the plan wins by about its mean margin (+8).
Writes assets/sharks_before.json and assets/sharks_after.json.
"""
import argparse
import json
import os

import _paths
import numpy as np
import torch

torch.set_num_threads(1)
from aflsim.analyst import v2                                              # noqa: E402
from aflsim.bots.registry import load_bot                                  # noqa: E402
from aflsim.engine import run_match                                        # noqa: E402
from aflsim.games import get_game                                          # noqa: E402
from aflsim.value.function import ValueFunction                            # noqa: E402

SHARKS = "ladder/climb/round_36a"
PLAN = os.path.join(_paths.HOME, "experiments", "analyst", "v2_sharks", "plans", "v2_sharks_open.py")
MODEL = "value_pos_29a"
SECONDS = 240.0
PIDS = ["A%d" % i for i in range(1, 9)] + ["B%d" % i for i in range(1, 9)]
TARGET = {"before": -25.4, "after": 8.0}                                  # mean margins in the official grade


def play(power, seed, on_state=None, record="none"):
    g = get_game("afl8"); r = g.make_rules(SECONDS)
    return run_match(g, load_bot(power, "A", r, seed), load_bot(SHARKS, "B", r, seed + 1000), r, seed, on_state=on_state, record=record)


def margin(ep):
    st = ep["stats"]; return st["score_A"] - st["score_B"]


def record(power, seed, name, vf, enc):
    dec = []
    log = play(power, seed, lambda game, state: dec.append([round(float(state["time"]), 2), round(vf.of_state(state), 3)]), "frames")
    frames = log["frames"][::2]
    P = np.array([[c for pid in PIDS for c in f["pos"][pid]] for f in frames])
    goals = []; last = {"A": 0, "B": 0}
    for f in log["frames"]:
        for t in "AB":
            d = f["score"][t] - last[t]
            if d:
                goals.append({"t": round(f["t"], 1), "team": t, "pts": d})
        last = dict(f["score"])
    return {"seed": seed, "seconds": SECONDS, "a": name, "b": "Sharks", "dt": round(frames[1]["t"] - frames[0]["t"], 3), "pids": PIDS,
            "t0": frames[0]["t"], "p": np.round(P * 10).astype(int).ravel().tolist(), "n": len(frames),
            "ball": [[round(f["ball"][0] * 10), round(f["ball"][1] * 10), round((f.get("height") or 0) * 10)] for f in frames],
            "state": "".join({"held": "h", "flight": "f", "loose": "l"}.get(f["state"], "x") for f in frames),
            "holder": [PIDS.index(f["holder"]) if f["holder"] in PIDS else -1 for f in frames],
            "scores": goals, "final": [last["A"], last["B"]], "value": dec}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--search", type=int, default=30); ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    seed = a.seed
    if seed is None:
        best = None
        for k in range(a.search):
            s = v2.GRADE_SEED0 + k
            mb, ma = margin(play(v2.POWER, s)), margin(play(PLAN, s))
            cost = abs(mb - TARGET["before"]) + abs(ma - TARGET["after"]) + (100 if mb >= 0 or ma <= 0 else 0)
            print(s, "before", mb, "after", ma, "cost", round(cost, 1), flush=True)
            if best is None or cost < best[0]:
                best = (cost, s)
        seed = best[1]
    print("chosen seed", seed, flush=True)
    vf = ValueFunction(MODEL); vf.model.eval(); enc = get_game("afl8").encoder()
    for key, power, name in (("before", v2.POWER, "Power"), ("after", PLAN, "Power (Claude's plan)")):
        out = record(power, seed, name, vf, enc)
        p = os.path.join(_paths.ASSETS, "sharks_%s.json" % key)
        json.dump(out, open(p, "w"), separators=(",", ":"))
        print(key, out["final"], os.path.getsize(p) // 1024, "KB", flush=True)


if __name__ == "__main__":
    main()
