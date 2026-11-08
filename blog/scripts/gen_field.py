"""What the network learned, measured on its own data: P(next goal) by where the ball is, labels and network side by
side, and calibration on the held-out games.

    python blog/scripts/gen_field.py
"""
import glob
import json
import os

import _paths
import numpy as np
import torch

torch.set_num_threads(2)
from aflsim.games.afl8.encode import FEATURE_NAMES                         # noqa: E402
from aflsim.value.model import load_model                                  # noqa: E402

D = "data/afl8/value_pos_29a"; CELL = 7.0
MODEL = "models/afl8/value_pos_29a.pt"
MC = "experiments/value_function/results/mc_takeover_29a"          # 100-rollout truth for sampled positions (round_29a takeover)
F = {n: i for i, n in enumerate(FEATURE_NAMES)}


def probs(m, X):
    out = np.empty(len(X), np.float32)
    with torch.no_grad():
        for i in range(0, len(X), 65536):
            out[i:i + 65536] = torch.sigmoid(m(torch.from_numpy(X[i:i + 65536].astype(np.float32))).reshape(-1)).numpy()
    return out


def main():
    m, meta = load_model(MODEL); m.eval()
    Xs, Ys, Gs = [], [], []
    for s in sorted(glob.glob(os.path.join(D, "shard_*.npz"))):
        d = np.load(s); Xs.append(d["X"]); Ys.append(d["y"]); Gs.append(d["game_id"])
    X = np.concatenate(Xs); y = np.concatenate(Ys); g = np.concatenate(Gs)
    print(X.shape, flush=True)
    pred = probs(m, X)
    bx = X[:, F["ball_x"]].astype(np.float32); by = X[:, F["ball_y"]].astype(np.float32)
    print("raw ball_x", float(bx.min()), float(bx.max()), "ball_y", float(by.min()), float(by.max()), flush=True)
    bx = (bx + 1) * 70.0; by = by * 70.0                                    # "my" frame, attacking +x, scaled to [-1, 1] by half the length
    nx, ny = 20, 14
    ix = np.clip((bx / (140 / nx)).astype(int), 0, nx - 1); iy = np.clip(((by + 50) / (100 / ny)).astype(int), 0, ny - 1)
    tabs = {"all": np.ones(len(X), bool), "mine": X[:, F["poss_mine"]] > .5, "theirs": X[:, F["poss_theirs"]] > .5, "loose": X[:, F["poss_nobody"]] > .5}
    field = {}
    for name, mask in tabs.items():
        n = np.zeros((ny, nx)); sy = np.zeros((ny, nx)); sp = np.zeros((ny, nx))
        np.add.at(n, (iy[mask], ix[mask]), 1); np.add.at(sy, (iy[mask], ix[mask]), y[mask]); np.add.at(sp, (iy[mask], ix[mask]), pred[mask])
        ok = n >= 40
        field[name] = {"n": n.astype(int).tolist(), "label": np.where(ok, sy / np.maximum(n, 1), -1).round(3).tolist(),
                       "net": np.where(ok, sp / np.maximum(n, 1), -1).round(3).tolist(), "rows": int(mask.sum())}
    test = (g % 20) == 0
    bins = np.linspace(0, 1, 21); k = np.clip(np.digitize(pred[test], bins) - 1, 0, 19); cal = []
    for b in range(20):
        s = k == b
        if s.sum() >= 50:
            cal.append({"p": round(float(pred[test][s].mean()), 4), "y": round(float(y[test][s].mean()), 4), "n": int(s.sum())})
    yt, pt = y[test].astype(np.float64), np.clip(pred[test].astype(np.float64), 1e-6, 1 - 1e-6)
    bce = float(-(yt * np.log(pt) + (1 - yt) * np.log(1 - pt)).mean()); base = float(yt.mean())
    bce0 = float(-(yt * np.log(base) + (1 - yt) * np.log(1 - base)).mean())
    acc = float(((pt > .5) == (yt > .5)).mean())
    hist = np.histogram(pred[test], bins=bins)[0].tolist()

    st = np.load(MC + "_states.npz", allow_pickle=True)
    mc = json.load(open(MC + ".json"))["rows"]
    v = (probs(m, st["x_a"]) + 1 - probs(m, st["x_b"])) / 2
    print("states", len(v), "rows", len(mc), flush=True)
    rows = [{"nn": round(float(v[i]), 3), "mc": round(float(r["v_mc"]), 3), "n": r["n_goal"], "kind": r["kind"]} for i, r in enumerate(mc[:len(v)])]
    a = np.array([r["nn"] for r in rows]); b = np.array([r["mc"] for r in rows])
    out = {"nx": nx, "ny": ny, "field": field, "rows": int(len(X)), "test_rows": int(test.sum()), "calibration": cal, "hist": hist,
           "test_bce": round(bce, 4), "coin_bce": round(bce0, 4), "test_acc": round(acc, 4),
           "mc": rows, "mc_r": round(float(np.corrcoef(a, b)[0, 1]), 3), "mc_mae": round(float(np.abs(a - b).mean()), 3)}
    p = os.path.join(_paths.ASSETS, "field.json")
    json.dump(out, open(p, "w"), separators=(",", ":"))
    print({k: v for k, v in out.items() if k not in ("field", "calibration", "mc", "hist")}, os.path.getsize(p) // 1024, "KB")


if __name__ == "__main__":
    main()
