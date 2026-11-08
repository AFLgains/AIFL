"""The challenge grader: can your bot beat the published target?

    python challenge/grade.py path/to/my_bot.py                  # AFL8: against round_29a
    python challenge/grade.py path/to/my_bot.py --game afl18     # AFL18: against zoo:rules
    python challenge/grade.py path/to/my_bot.py --quick          # a fast check: 20 seeds, no rating

The grader does four things (challenge/README.md gives the rules in full):
  1. CHECK    the bot loads, gives no errors, and plays the same game again from the same seed;
  2. CLOCK    the bot's time for each decision (mean and maximum) is inside the limits;
  3. MATCH    the bot plays the target on N seeds from both ends (2N games): the win rate, a draw counts as half;
  4. RATING   the bot plays each bot of the reference pool, and gets an Elo rating against the pool's fixed ratings.

Nothing is written to the results store. --json writes the full report to a file.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from aflsim.bots.base import TeamController                                          # noqa: E402
from aflsim.bots.registry import bot_hash, load_bot                                  # noqa: E402
from aflsim.engine import run_match                                                  # noqa: E402
from aflsim.exec import Serial, make_executor                                        # noqa: E402
from aflsim.games import engine_version, get_game                                    # noqa: E402
from aflsim.match.rating import bootstrap_one, elo_gap, fit_one                      # noqa: E402

SECONDS = 240.0                                                     # game length, both games
TARGETS = {"afl8": os.path.join(HERE, "afl8", "round_29a.py"), "afl18": "zoo:rules"}
SEEDS = 200                                                         # match seeds (x2 ends = 400 games)
ELO_SEEDS = 20                                                      # seeds per pool opponent (x2 ends = 40 games)
PASS_SCORE = 0.55                                                   # beat the target: win rate at least this over the 400 games
MEAN_MS = 50.0                                                      # limit: mean time per decision
MAX_MS = 1000.0                                                     # limit: longest single decision
DETERMINISM_SEEDS = 3                                               # seeds replayed in this process (x2 ends)


def reference_path(game):
    return os.path.join(HERE, game, "reference.json")


def resolve(spec):
    """A reference-pool spec ("zoo:x", or a path relative to the repository) as load_bot takes it."""
    return spec if spec.startswith("zoo:") else os.path.join(ROOT, spec)


class Guarded(TeamController):
    """The challenger as the engine sees it: a private deep copy of every state (so it cannot change what the other
    team sees), no hook to the true game object (observe_game is not passed on), and a clock on every decision."""

    def __init__(self, bot):
        super().__init__(bot.team)
        self._bot = bot; self.name = bot.name
        self.calls = 0; self.total_s = 0.0; self.worst_s = 0.0

    def choose_actions(self, state, problems):
        mine = copy.deepcopy(state)
        t = time.perf_counter()
        out = self._bot.choose_actions(mine, list(problems))
        dt = time.perf_counter() - t
        self.calls += 1; self.total_s += dt; self.worst_s = max(self.worst_s, dt)
        return out

    @property
    def last_problems(self):
        return self._bot.last_problems

    @property
    def errors(self):
        return self._bot.errors


def play(job):
    """One game. job = (game, challenger spec, opponent label, opponent spec, seed, challenger's team "A" | "B").
    Seeding is the platform's: team A's bot gets `seed`, team B's bot `seed + 1000`, and the engine `seed`."""
    game, chal, opp_label, opp, seed, side = job
    g = get_game(game); rules = g.make_rules(SECONDS)
    other = "B" if side == "A" else "A"
    specs = {side: chal, other: opp}
    bots = {t: load_bot(specs[t], t, rules, seed if t == "A" else seed + 1000, game) for t in "AB"}
    guard = Guarded(bots[side]); bots[side] = guard
    ep = run_match(g, bots["A"], bots["B"], rules, seed, None, record="none")
    st = ep["stats"]; me, them = st["score_" + side], st["score_" + other]
    return {"opp": opp_label, "seed": seed, "side": side, "for": me, "against": them,
            "score": 1.0 if me > them else 0.0 if me < them else 0.5, "result": st["result"],
            "errors": len(guard.errors), "first_error": guard.errors[0] if guard.errors else "",
            "calls": guard.calls, "total_s": guard.total_s, "worst_s": guard.worst_s}


def jobs_against(game, chal, label, spec, seed0, n):
    out = []
    for k in range(n):
        out.append((game, chal, label, spec, seed0 + k, "A"))
        out.append((game, chal, label, spec, seed0 + k, "B"))
    return out


def summary(rows):
    n = len(rows); w = sum(r["score"] == 1.0 for r in rows); d = sum(r["score"] == 0.5 for r in rows)
    s = (w + 0.5 * d) / n
    se = math.sqrt(max(s * (1 - s), 1e-6) / n)
    return {"games": n, "won": w, "lost": n - w - d, "drawn": d, "win_rate": s, "se": se,
            "low95": max(0.0, s - 1.96 * se), "high95": min(1.0, s + 1.96 * se),
            "points_for": sum(r["for"] for r in rows), "points_against": sum(r["against"] for r in rows)}


def run(fn, jobs, parallel, label):
    ex = make_executor(parallel); out = []; t0 = time.time()
    for i, row in enumerate(ex.imap(fn, jobs), 1):
        out.append(row)
        if i % 20 == 0 or i == len(jobs):
            print("  %s: %d of %d games (%.0f s)" % (label, i, len(jobs), time.time() - t0), flush=True)
    if len(out) != len(jobs):
        raise SystemExit("FAIL: %d of %d games did not finish (a worker crashed)" % (len(jobs) - len(out), len(jobs)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Grade a bot against the public challenge.")
    ap.add_argument("bot", help="path to your bot file (one .py file that defines class Bot)")
    ap.add_argument("--game", default="afl8", choices=sorted(TARGETS))
    ap.add_argument("--seed0", type=int, default=1, help="first seed (default 1: the public self-test seeds; official grading uses a secret seed0)")
    ap.add_argument("--seeds", type=int, default=SEEDS, help="match seeds against the target, each from both ends (default %d)" % SEEDS)
    ap.add_argument("--elo-seeds", type=int, default=ELO_SEEDS, help="seeds against each other pool bot (default %d)" % ELO_SEEDS)
    ap.add_argument("--no-rating", action="store_true", help="skip the Elo rating (match only)")
    ap.add_argument("--quick", action="store_true", help="20 seeds, no rating: a fast check, not a grade")
    ap.add_argument("--parallel", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--json", help="write the full report to this file")
    a = ap.parse_args(argv)
    if a.quick:
        a.seeds = 20; a.no_rating = True

    game = a.game; g = get_game(game); chal = os.path.abspath(a.bot); target = TARGETS[game]
    official = (a.seeds == SEEDS and a.elo_seeds == ELO_SEEDS and not a.no_rating)
    report = {"game": game, "engine_version": engine_version(g), "seconds": SECONDS, "bot": os.path.basename(chal),
              "bot_hash": bot_hash(chal, game), "seed0": a.seed0, "seeds": a.seeds, "full_grade": official, "failures": []}
    fail = report["failures"]

    ref = None
    if not a.no_rating:
        with open(reference_path(game), encoding="utf-8") as f:
            ref = json.load(f)
        if ref["engine_version"] != engine_version(g) or ref["seconds"] != SECONDS:
            raise SystemExit("The reference pool was built for engine v%s, %s s games: rebuild it (challenge/reference.py)." % (ref["engine_version"], ref["seconds"]))
        for label, b in ref["bots"].items():
            if bot_hash(resolve(b["spec"]), game) != b["hash"]:
                raise SystemExit("The reference bot %s has changed since the pool was rated: rebuild it (challenge/reference.py)." % label)

    print("%s | engine v%s | %d s games | bot %s (%s)" % (game, engine_version(g), SECONDS, report["bot"], report["bot_hash"][:12]))

    # 1. CHECK: it loads, and it is not allowed the game hook
    rules = g.make_rules(SECONDS)
    probe = load_bot(chal, "A", rules, a.seed0, game).inner
    if hasattr(probe, "observe_game"):
        fail.append("the bot defines observe_game (access to the true game object is not allowed)")

    # 3. MATCH against the target
    tlabel = "round_29a" if game == "afl8" else target
    print("Match: %d games against %s" % (2 * a.seeds, tlabel))
    rows = run(play, jobs_against(game, chal, tlabel, target, a.seed0, a.seeds), a.parallel, "match")

    # 1. CHECK (continued): replay the first seeds here, and compare
    replay = Serial().map(play, jobs_against(game, chal, tlabel, target, a.seed0, min(DETERMINISM_SEEDS, a.seeds)))
    first = {(r["seed"], r["side"]): (r["for"], r["against"]) for r in rows}
    diff = [r for r in replay if first.get((r["seed"], r["side"])) != (r["for"], r["against"])]
    if diff:
        fail.append("not deterministic: seed %d (team %s) gave a different game when it was played again" % (diff[0]["seed"], diff[0]["side"]))

    m = summary(rows)
    report["match"] = m
    report["match"]["target"] = tlabel
    report["match"]["beats_target"] = m["win_rate"] >= PASS_SCORE

    # 4. RATING against the reference pool (the match games against the target count too)
    all_rows = list(rows)
    if ref is not None:
        others = [(lb, b) for lb, b in ref["bots"].items() if lb != tlabel]
        jobs = []
        for k, (lb, b) in enumerate(others):
            jobs += jobs_against(game, chal, lb, resolve(b["spec"]), a.seed0, a.elo_seeds)
        print("Rating: %d games against %d other pool bots" % (len(jobs), len(others)))
        all_rows += run(play, jobs, a.parallel, "rating")
        ratings = {lb: b["rating"] for lb, b in ref["bots"].items()}
        res = [(r["opp"], r["score"]) for r in all_rows]
        elo = fit_one(res, ratings); lo, hi = bootstrap_one(res, ratings, n=500)
        per = {}
        for lb in ratings:
            rs = [r for r in all_rows if r["opp"] == lb]
            if rs:
                s = summary(rs); per[lb] = {"games": s["games"], "win_rate": round(s["win_rate"], 3), "their_rating": round(ratings[lb])}
        report["rating"] = {"elo": elo, "low95": lo, "high95": hi, "games": len(all_rows), "target_rating": ratings.get(tlabel), "by_opponent": per}

    # 2. CLOCK and errors, over every game played
    calls = sum(r["calls"] for r in all_rows); total = sum(r["total_s"] for r in all_rows); worst = max(r["worst_s"] for r in all_rows)
    errors = sum(r["errors"] for r in all_rows)
    report["clock"] = {"decisions": calls, "mean_ms": 1000 * total / max(calls, 1), "max_ms": 1000 * worst}
    report["errors"] = errors
    if errors:
        e = next(r for r in all_rows if r["errors"])
        fail.append("%d errors (a bot error is a lost turn), first: %s" % (errors, e["first_error"]))
    if report["clock"]["mean_ms"] > MEAN_MS:
        fail.append("too slow: mean %.1f ms per decision (limit %.0f ms)" % (report["clock"]["mean_ms"], MEAN_MS))
    if report["clock"]["max_ms"] > MAX_MS:
        fail.append("too slow: one decision took %.0f ms (limit %.0f ms)" % (report["clock"]["max_ms"], MAX_MS))
    report["valid"] = not fail

    # the report
    print()
    print("MATCH against %s: %d games, won %d, lost %d, drawn %d" % (tlabel, m["games"], m["won"], m["lost"], m["drawn"]))
    print("  win rate %.1f %% (95 %% interval %.1f to %.1f %%), points %d to %d" % (100 * m["win_rate"], 100 * m["low95"], 100 * m["high95"], m["points_for"], m["points_against"]))
    if 0.0 < m["win_rate"] < 1.0:
        print("  Elo gap to %s from this match: %+.0f" % (tlabel, elo_gap(m["win_rate"])))
    print("  beats the target (at least %.0f %%): %s" % (100 * PASS_SCORE, "YES" if m["win_rate"] >= PASS_SCORE else "no"))
    if "rating" in report:
        r = report["rating"]
        print("RATING: %.0f (95 %% interval %.0f to %.0f), from %d games; %s is %.0f on this scale" % (r["elo"], r["low95"], r["high95"], r["games"], tlabel, r["target_rating"]))
    print("CLOCK: %d decisions, mean %.1f ms, longest %.0f ms (limits %.0f ms and %.0f ms)" % (calls, report["clock"]["mean_ms"], report["clock"]["max_ms"], MEAN_MS, MAX_MS))
    print("ERRORS: %d" % errors)
    print()
    if fail:
        print("INVALID:"); [print("  - " + x) for x in fail]
    elif not official:
        print("Valid. This was not a full grade (a full grade uses the default --seeds and --elo-seeds, with the rating).")
    else:
        print("Valid. Full grade with seed0 = %d." % a.seed0)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print("Report: %s" % a.json)
    return 0 if not fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
