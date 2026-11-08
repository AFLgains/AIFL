import json, sys
sys.path.insert(0, "/ws/analysis")
import numpy as np, pandas as pd
from common import STRONG
lab = lambda x: x if x in ("Sharks", "Power") else ("strong" if x in STRONG else "other")
d = pd.read_pickle("/ws/analysis/disp_hold.pkl")
k = d[(d.type == "kick") & (d.shot != True) & (d.dist >= 15)].copy()
k["adv"] = k.rel_d_opp - k.rel_d_own
bins = [-60, -5, -2, 0, 2, 4, 6, 8, 10, 14, 60]
k["ab"] = pd.cut(k.adv, bins)
g = k.groupby("ab", observed=True).agg(kept=("kept", "mean"), n=("kept", "size"), mid=("adv", "median"))
out = {"curve": [{"lo": float(iv.left), "hi": float(iv.right), "mid": float(r.mid), "kept": float(r.kept), "n": int(r.n)} for iv, r in g.iterrows()],
       "kicks": int(len(k)), "groups": {}}
for grp in ("Power v Sharks", "strong v Sharks", "Sharks v Power"):
    a, b = grp.split(" v ")
    q = k[(k.club.map(lab) == a) & (k.opp.map(lab) == b)]
    h, e = np.histogram(q.adv.clip(-15, 25), bins=np.arange(-15, 27.5, 2.5))
    out["groups"][grp] = {"n": int(len(q)), "over6": float((q.adv > 6).mean()), "le0": float((q.adv <= 0).mean()),
                          "kept": float(q.kept.mean()), "hist": [int(x) for x in h], "edges": [float(x) for x in e]}
print(json.dumps(out))
