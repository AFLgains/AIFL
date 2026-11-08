"""One real game, with everything the replay figures need: positions, orders, the network's rating at every decision,
its hidden activations, how much each player moved the rating, and from three moments of the game, what-if maps and
rollouts (the labelling recipe, with the ball's path kept).

    python blog/scripts/gen_match.py --seeds 16 --rollouts 64
"""
import argparse
import base64
import dataclasses
import json
import os

import _paths
import numpy as np
import torch

torch.set_num_threads(1)
from aflsim.bots.registry import load_bot                                  # noqa: E402
from aflsim.engine import decide_and_advance, run_match                    # noqa: E402
from aflsim.games import get_game                                          # noqa: E402
from aflsim.games.afl8.analysis import place_player                        # noqa: E402
from aflsim.games.afl8.encode import FEATURE_NAMES                         # noqa: E402
from aflsim.games.afl8.ground import Oval                                  # noqa: E402
from aflsim.value.function import ValueFunction                            # noqa: E402

A, B, TAKEOVER = "ladder/climb/round_36a", "ladder/climb/round_29a", "ladder/climb/round_29a"   # TAKEOVER: the labelling bot
MODEL = "value_pos_29a"
SECONDS = 240.0
PIDS = ["A%d" % i for i in range(1, 9)] + ["B%d" % i for i in range(1, 9)]
ACT = {"MOVE": "M", "HOLD": "O", "KICK": "K", "HANDBALL": "H", "ATTEMPT_POSSESSION": "P", "ATTEMPT_MARK": "A", "SPOIL": "S", "TACKLE": "T"}


def play(seed, on_state=None):
    g = get_game("afl8"); r = g.make_rules(SECONDS)
    return run_match(g, load_bot(A, "A", r, seed), load_bot(B, "B", r, seed + 1000), r, seed, on_state=on_state, record="frames")


def drama(log):
    """Close at the end, plenty of goals, and the lead changing hands."""
    lead = 0; changes = 0; goals = 0; last = (0, 0)
    for f in log["frames"]:
        s = (f["score"]["A"], f["score"]["B"])
        goals += (s[0] - last[0] >= 6) + (s[1] - last[1] >= 6); last = s
        d = (s[0] > s[1]) - (s[0] < s[1])
        if d and d != lead:
            changes += bool(lead); lead = d
    return changes * 3 + goals - abs(last[0] - last[1]) / 4.0, changes, goals, last


def player_slots():
    idx = []
    for pid in PIDS:
        tag = ("mine" if pid[0] == "A" else "opp") + pid[1]
        idx.append([i for i, n in enumerate(FEATURE_NAMES) if n.startswith(tag + "_")])
    return idx


def probe(vf, x, slots):
    """One forward and backward pass from A's side: the hidden activations, and how much each player's features move the logit."""
    m = vf.model; acts = []
    hooks = [l.register_forward_hook(lambda _m, _i, o: acts.append(o.detach()[0].numpy().copy())) for l in m.net if isinstance(l, torch.nn.ReLU)]
    t = torch.tensor(x, dtype=torch.float32)[None].requires_grad_(True)
    m(t).sum().backward()
    for h in hooks:
        h.remove()
    std = m.std.numpy().ravel() if hasattr(m, "std") else np.ones(len(x))
    g = np.abs(t.grad[0].numpy()) * std
    return acts, np.array([g[s].sum() for s in slots])


def rollouts(clone, n, seed0):
    """The labelling recipe: the takeover bot plays both sides from here until a goal. Keeps the ball's path."""
    out = []
    for k in range(n):
        seed = seed0 + k
        game = clone.clone()
        game.r = dataclasses.replace(game.r, episode_seconds=game.t + 120.0)
        game.rng = np.random.default_rng(seed)
        rules = game.r
        ctls = {"A": load_bot(TAKEOVER, "A", rules, seed), "B": load_bot(TAKEOVER, "B", rules, seed + 500000)}
        problems = {"A": [], "B": []}; recent = []; t0 = game.t
        path = [[round(float(game.ball_pos[0]), 1), round(float(game.ball_pos[1]), 1), 0.0]]
        who = None
        while not game.done:
            prev = dict(game.score)
            recent, _ = decide_and_advance(game, ctls, problems, recent)
            path.append([round(float(game.ball_pos[0]), 1), round(float(game.ball_pos[1]), 1), round(float(game.t - t0), 1)])
            da, db = game.score["A"] - prev["A"], game.score["B"] - prev["B"]
            if da >= 6 or db >= 6:
                who = "A" if da >= 6 else "B"
                path[-1][0] = 140.0 if who == "A" else 0.0                 # the ball restarts at the centre after a goal: end the path at the goal line
                path[-1][1] = float(np.clip(path[-2][1], -3, 3))
                break
        out.append({"who": who, "t": path[-1][2], "path": path})
    return out


def whatif(vf, clone, step=5.0):
    """Teleport the carrier (and ball) to every spot on the ground, everyone else where they stand, and rate it."""
    pid = clone.holder
    oval = Oval(clone.r)
    xs = np.arange(0, 140.01, step); ys = np.arange(-50, 50.01, step); grid = []
    for y in ys:
        row = []
        for x in xs:
            if not oval.inside((x, y)):
                row.append(None); continue
            c = clone.clone(); place_player(c, pid, (x, y))
            row.append(round(vf(c, "A"), 3))
        grid.append(row)
    return {"x0": 0, "y0": -50, "step": step, "nx": len(xs), "ny": len(ys), "v": grid}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--seeds", type=int, default=16); ap.add_argument("--rollouts", type=int, default=64)
    ap.add_argument("--seed", type=int, default=None); a = ap.parse_args()
    best = a.seed
    if best is None:
        scored = []
        for s in range(1, a.seeds + 1):
            d = drama(play(s)); scored.append((d[0], s, d[1:])); print(s, d, flush=True)
        best = max(scored)[1]
    print("chosen seed", best, flush=True)

    vf = ValueFunction(MODEL); vf.model.eval(); enc = get_game("afl8").encoder()
    slots = player_slots(); dec = []

    def on_state(game, state):
        x = enc.encode_state(state, "A"); acts, sens = probe(vf, x, slots)
        dec.append({"t": float(state["time"]), "v": vf.of_state(state), "acts": acts, "sens": sens, "clone": game.clone()})

    log = play(best, on_state)
    frames = log["frames"][::2]
    P = np.array([[c for pid in PIDS for c in f["pos"][pid]] for f in frames])
    out = {"seed": best, "seconds": SECONDS, "a": "round_36a", "b": "round_29a", "dt": round(frames[1]["t"] - frames[0]["t"], 3),
           "pids": PIDS, "t0": frames[0]["t"], "p": np.round(P * 10).astype(int).ravel().tolist(), "n": len(frames),
           "ball": [[round(f["ball"][0] * 10), round(f["ball"][1] * 10), round((f.get("height") or 0) * 10)] for f in frames],
           "state": "".join({"held": "h", "flight": "f", "loose": "l"}.get(f["state"], "x") for f in frames),
           "holder": [PIDS.index(f["holder"]) if f["holder"] in PIDS else -1 for f in frames],
           "score": [[f["score"]["A"], f["score"]["B"]] for f in frames]}
    goals = []; last = {"A": 0, "B": 0}
    for f in log["frames"]:
        for t in "AB":
            d = f["score"][t] - last[t]
            if d:
                goals.append({"t": round(f["t"], 1), "team": t, "pts": d})
        last = dict(f["score"])
    out["scores"] = goals
    out["final"] = [last["A"], last["B"]]

    orders = []                                                            # at every decision: each player's action letter, target and pace
    for e in log["decisions"]:
        row = {}
        for team in "AB":
            for act in e["teams"][team]["actions"]:
                tgt = act.get("target")
                row[act["player"]] = [ACT.get(act["action"], "?"), None if tgt is None else round(tgt[0], 1), None if tgt is None else round(tgt[1], 1), (act.get("pace") or "run")[0]]
        orders.append({"t": round(e["t"], 2), "o": [row.get(p) for p in PIDS]})
    out["orders"] = orders
    out["value"] = [[round(d["t"], 2), round(d["v"], 3)] for d in dec]

    layers = []                                                            # the most active units of each hidden layer, one byte per unit per decision
    for li in range(3):
        M = np.stack([d["acts"][li] for d in dec]); keep = {0: 80, 1: 80, 2: 48}[li]
        idx = np.argsort(-M.var(0))[:keep]; idx = idx[np.argsort(-M[:, idx].mean(0))]
        S = M[:, idx]; S = S / np.maximum(np.percentile(S, 99, axis=0), 1e-6)
        layers.append({"units": int(M.shape[1]), "keep": keep, "b64": base64.b64encode((np.clip(S, 0, 1) * 255).astype(np.uint8).tobytes()).decode()})
    out["layers"] = layers
    S = np.stack([d["sens"] for d in dec]); S = S / S.max(1, keepdims=True)
    out["sens"] = np.round(S * 99).astype(int).ravel().tolist()
    p = os.path.join(_paths.ASSETS, "match.json")
    json.dump(out, open(p, "w"), separators=(",", ":"))
    print("match.json", os.path.getsize(p) // 1024, "KB", out["final"], flush=True)

    def pick(lo, hi):
        c = [d for d in dec if d["clone"].holder and d["clone"].holder[0] == "A" and d["clone"].ball_state == "held" and d["clone"].set_play is None
             and lo <= d["clone"].ball_pos[0] <= hi and 0.42 <= d["v"] <= 0.72 and 20 < d["t"] < 220]
        return c[len(c) // 2] if c else None

    moments = []                                                           # three moments with team A on the ball
    for name, lo, hi in (("Deep in defence", 18, 45), ("Through the middle", 60, 85), ("Inside forward fifty", 95, 118)):
        d = pick(lo, hi)
        if d is None:
            print("no moment for", name, flush=True); continue
        c = d["clone"]; rs = rollouts(c, a.rollouts, 900000 + int(d["t"] * 10))
        na = sum(r["who"] == "A" for r in rs); nb = sum(r["who"] == "B" for r in rs)
        moments.append({"name": name, "t": round(d["t"], 1), "v": round(d["v"], 3), "holder": c.holder, "ball": [round(float(c.ball_pos[0]), 1), round(float(c.ball_pos[1]), 1)],
                        "pos": {q: [round(float(c.players[q].pos[0]), 1), round(float(c.players[q].pos[1]), 1)] for q in PIDS},
                        "a": na, "b": nb, "none": len(rs) - na - nb, "rollouts": rs, "whatif": whatif(vf, c)})
        print(name, d["t"], round(d["v"], 3), "rollouts A", na, "B", nb, flush=True)
    p = os.path.join(_paths.ASSETS, "moments.json")
    json.dump({"bot": TAKEOVER.rsplit("/", 1)[-1], "moments": moments}, open(p, "w"), separators=(",", ":"))
    print("moments.json", os.path.getsize(p) // 1024, "KB", flush=True)


if __name__ == "__main__":
    main()
