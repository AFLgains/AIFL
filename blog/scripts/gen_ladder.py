"""The climb on one scale (Figure 4).

The archived 120 s ladder (engine v1) holds every round of the climb, so all bots are fitted together from its games.
The newer v2 ladder is not used: its top rating is inflated by how few games separate the champion from the field.

    python blog/scripts/gen_ladder.py
"""
import json
import os
import re

import _paths
from aflsim.match import rating as R


def main():
    d = json.load(open("experiments/archive/afl_llm_play_progress_120s.json"))
    ms = d["matches"]
    print(len(ms), "games", flush=True)
    fit = R.fit_ratings
    ratings = fit(ms)
    print(sorted(ratings.items(), key=lambda kv: -kv[1])[:6], flush=True)
    bots = []
    for name, elo in ratings.items():
        g = re.match(r"(climb|red|blue)_round_(\d+)([a-z]?)", name)
        n = sum(1 for m in ms if name in (m["a"], m["b"]))
        if g:
            bots.append({"name": name.replace("climb_", ""), "family": g.group(1), "round": int(g.group(2)), "elo": round(elo), "games": n})
        else:
            bots.append({"name": name, "family": "zoo", "round": None, "elo": round(elo), "games": n})
    p = os.path.join(_paths.ASSETS, "ladder.json")
    json.dump({"games": len(ms), "bots": bots}, open(p, "w"), separators=(",", ":"))
    print(os.path.getsize(p) // 1024, "KB")


if __name__ == "__main__":
    main()
