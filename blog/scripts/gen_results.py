"""The analyst results for Figure 14, Tables 1 and 2, and the copies of the analysts' own reports and plans.

    python blog/scripts/gen_results.py

Reads the official grades (experiments/analyst/<run>/grades.json), the cross-swap (cross_grades.json) and the zoo
pool regrade (pool_regrade.json) from the private checkout. Writes assets/results.json, and copies each club's
report.html and each plan.md to assets/reports/. Every win rate counts a draw as half a win.
"""
import json
import os
import shutil

from _paths import ASSETS, HOME

A = os.path.join(HOME, "experiments", "analyst")
ROWS = [("giants", "v2_giants", "budget", "Giants", "zoo:rules"), ("eagles", "v2_eagles", "budget", "Eagles", "zoo:ontario"),
        ("sharks", "v2_sharks", "budget", "Sharks", "round_36a"), ("sharks_open", "v2_sharks", "open", "Sharks", "round_36a")]


def wld(s):
    return {"w": s["won"], "l": s["lost"], "d": s["drawn"], "score": s["win_rate"], "margin": s["margin"]}


RUNS_DIR = os.environ.get("AFL_ANALYSIS_RUNS", r"C:\projects\afl_analysis_runs")
NOTES = {   # one note per changed block, from the plan's own reasons
    "giants": ["Shoot from up to 45 m, not 38 m: the Giants let long shots through.",
               "Close down the Giants' carrier: the nearest Power player within 12 m tackles. This came from a test with the rating tool.",
               "Kick to the receiver, not 3 m in front of him: that is where the Giants' defender stands."],
    "eagles": ["A teammate is free only with no opponent within 5 m: the Eagles' defenders stand 3.3 m from their forward.",
               "The forwards stand 35 m ahead of the ball, not 25 m, to pull the Eagles' man-markers deep.",
               "The covering midfielder stands 20 m behind the ball, not 10 m, where the Eagles' long kicks land."],
    "sharks": ["A teammate is free only with no opponent within 7 m: the Sharks' defenders stand 2.7–3.1 m from the Power's forwards.",
               "Kick to where the receiver will be, not to where he stands. With no kick on and no opponent near, run on for up to 0.8 s before a short handball."],
}


def diffs():
    """Each limited plan against the original Power, as blocks of changed lines with one line of context."""
    import difflib, re
    out = {}
    for club in ("giants", "eagles", "sharks"):
        base = open(os.path.join(RUNS_DIR, "v2_%s_budget" % club, "botkit", "_baseline", "power.py"), encoding="utf-8").read().splitlines()
        plan = open(os.path.join(A, "v2_" + club, "plans", "v2_%s_budget.py" % club), encoding="utf-8").read().splitlines()
        hunks, cur = [], None
        for l in difflib.unified_diff(base, plan, n=1, lineterm=""):
            m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)", l)
            if m:
                cur = {"old": int(m.group(1)), "new": int(m.group(2)), "lines": []}; hunks.append(cur); continue
            if cur is None or l.startswith(("---", "+++")):
                continue
            cur["lines"].append([l[0], l[1:]])
        assert len(hunks) == len(NOTES[club]), (club, len(hunks))
        for h, note in zip(hunks, NOTES[club]):
            h["note"] = note
        out[club] = hunks
    return out


def main():
    pool = json.load(open(os.path.join(A, "pool_regrade.json"), encoding="utf-8"))
    cross = json.load(open(os.path.join(A, "cross_grades.json"), encoding="utf-8"))
    zoo = [c for c in pool["kept"] if c.startswith("zoo:")]
    ladder = [c for c in pool["kept"] if not c.startswith("zoo:")]
    out = {"rows": {}, "zoo_clubs": zoo, "ladder_clubs": ladder, "games_per_club": pool["games_per_club"]}
    for key, run, arm, club, target in ROWS:
        g = json.load(open(os.path.join(A, run, "grades.json"), encoding="utf-8"))[arm]
        p = pool["plans"]["%s:%s" % (run, arm)]["by_club"]
        avg = lambda cs, k: sum(p[c][k] for c in cs) / len(cs)
        out["rows"][key] = {"club": club, "target": target, "limit": "3 changes" if arm == "budget" else "None",
                            "changes": g["budget"]["changes"], "lines": g["budget"]["lines"],
                            "before": wld(g["power_v_target"]), "plan": wld(g["plan_v_target"]),
                            "gain": g["uplift"], "gain_se": g["uplift_se_paired"],
                            "zoo": {"before": avg(zoo, "power"), "plan": avg(zoo, "plan")},
                            "ladder": {"before": avg(ladder, "power"), "plan": avg(ladder, "plan")}}
    sw = {}
    for ctl, tgt in (("v2_giants", "v2_eagles"), ("v2_eagles", "v2_giants")):
        r = cross["%s:budget@%s" % (ctl, tgt)]
        sw["%s_plan_v_%s" % (ctl[3:], tgt[3:])] = {"plan": r["summary"]["control"]["win_rate"], "before": r["summary"]["power"]["win_rate"]}
    out["cross"] = sw
    out["diffs"] = diffs()
    json.dump(out, open(os.path.join(ASSETS, "results.json"), "w", encoding="utf-8"), indent=1)

    rep = os.path.join(ASSETS, "reports"); os.makedirs(rep, exist_ok=True)
    for club in ("giants", "eagles", "sharks"):
        shutil.copyfile(os.path.join(A, "v2_" + club, "deliverables", "report.html"), os.path.join(rep, club + "_report.html"))
    for key, run, arm, _c, _t in ROWS:
        shutil.copyfile(os.path.join(A, run, "deliverables_" + arm, "plan.md"), os.path.join(rep, "%s_plan.md" % key))
    print("wrote results.json and %d files in assets/reports" % len(os.listdir(rep)))


if __name__ == "__main__":
    main()
