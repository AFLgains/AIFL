"""The challenge grader: how does your bot do against the benchmark?

    python challenge/grade.py path/to/my_bot.py                  # AFL8: against round_29a
    python challenge/grade.py path/to/my_bot.py --game afl18     # AFL18: against zoo:rules
    python challenge/grade.py path/to/my_bot.py --quick          # a fast check: 20 seeds (40 games)

The grader does three things (challenge/README.md gives the rules in full):
  1. CHECK    the bot loads, gives no errors, and plays the same game again from the same seed;
  2. CLOCK    the bot's time for each decision (mean and maximum) is inside the limits;
  3. MATCH    the bot plays the benchmark on N seeds from both ends (2N games). The result is the win rate (a draw
              counts as half) and the Elo difference to the benchmark that this win rate gives.

Nothing is written to the results store. --json writes the full report to a file.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from aflsim.bots.base import TeamController                                          # noqa: E402
from aflsim.bots.registry import load_bot                                            # noqa: E402
from aflsim.engine import run_match                                                  # noqa: E402
from aflsim.exec import Serial, make_executor                                        # noqa: E402
from aflsim.games import engine_version, get_game                                    # noqa: E402
from aflsim.match.rating import elo_gap                                              # noqa: E402

SECONDS = 240.0                                                     # game length, both games
BENCHMARKS = {"afl8": ("round_29a", os.path.join(HERE, "afl8", "round_29a.py")), "afl18": ("zoo:rules", "zoo:rules")}
SEEDS = 200                                                         # match seeds (x2 ends = 400 games)
PASS_SCORE = 0.55                                                   # beat the benchmark: win rate at least this over the 400 games
MEAN_MS = 50.0                                                      # limit: mean time per decision
MAX_MS = 1000.0                                                     # limit: longest single decision
DETERMINISM_SEEDS = 3                                               # seeds replayed in this process (x2 ends)


def code_hash(spec, game):
    """Fingerprint of a bot's code with line endings made the same (CRLF and LF give one hash), so the same file
    gives the same fingerprint on any system. The zoo bots are afl8's rules_zoo.py and rules_ai.py (and, for AFL18,
    the selection in afl18's controllers/zoo.py)."""
    if spec.startswith("zoo:"):
        games = os.path.dirname(os.path.dirname(os.path.abspath(get_game(game).__file__)))
        files = [os.path.join(games, "afl8", "controllers", "rules_zoo.py"), os.path.join(games, "afl8", "controllers", "rules_ai.py")]
        if game == "afl18":
            files.append(os.path.join(games, "afl18", "controllers", "zoo.py"))
    else:
        files = [spec]
    h = hashlib.sha256()
    for f in files:
        with open(f, "rb") as fh:
            h.update(fh.read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


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
    """One game. job = (game, challenger spec, benchmark spec, seed, challenger's team "A" | "B").
    Seeding is the platform's: team A's bot gets `seed`, team B's bot `seed + 1000`, and the engine `seed`."""
    game, chal, opp, seed, side = job
    g = get_game(game); rules = g.make_rules(SECONDS)
    other = "B" if side == "A" else "A"
    specs = {side: chal, other: opp}
    bots = {t: load_bot(specs[t], t, rules, seed if t == "A" else seed + 1000, game) for t in "AB"}
    guard = Guarded(bots[side]); bots[side] = guard
    ep = run_match(g, bots["A"], bots["B"], rules, seed, None, record="none")
    st = ep["stats"]; me, them = st["score_" + side], st["score_" + other]
    return {"seed": seed, "side": side, "for": me, "against": them,
            "score": 1.0 if me > them else 0.0 if me < them else 0.5, "result": st["result"],
            "errors": len(guard.errors), "first_error": guard.errors[0] if guard.errors else "",
            "calls": guard.calls, "total_s": guard.total_s, "worst_s": guard.worst_s}


def jobs_for(game, chal, opp, seed0, n):
    out = []
    for k in range(n):
        out.append((game, chal, opp, seed0 + k, "A"))
        out.append((game, chal, opp, seed0 + k, "B"))
    return out


def summary(rows):
    n = len(rows); w = sum(r["score"] == 1.0 for r in rows); d = sum(r["score"] == 0.5 for r in rows)
    s = (w + 0.5 * d) / n
    se = math.sqrt(max(s * (1 - s), 1e-6) / n)
    lo, hi = max(0.0, s - 1.96 * se), min(1.0, s + 1.96 * se)
    return {"games": n, "won": w, "lost": n - w - d, "drawn": d, "win_rate": s, "se": se, "low95": lo, "high95": hi,
            "elo": elo_gap(s), "elo_low95": elo_gap(lo), "elo_high95": elo_gap(hi),
            "points_for": sum(r["for"] for r in rows), "points_against": sum(r["against"] for r in rows)}


def run(jobs, parallel):
    ex = make_executor(parallel); out = []; t0 = time.time()
    for i, row in enumerate(ex.imap(play, jobs), 1):
        out.append(row)
        if i % 20 == 0 or i == len(jobs):
            print("  %d of %d games (%.0f s)" % (i, len(jobs), time.time() - t0), flush=True)
    if len(out) != len(jobs):
        raise SystemExit("FAIL: %d of %d games did not finish (a worker crashed)" % (len(jobs) - len(out), len(jobs)))
    return out


def elo_text(x):
    return "below -1200" if x <= -1199 else "above +1200" if x >= 1199 else "%+.0f" % x


def main(argv=None):
    ap = argparse.ArgumentParser(description="Grade a bot against the challenge benchmark.")
    ap.add_argument("bot", help="path to your bot file (one .py file that defines class Bot)")
    ap.add_argument("--game", default="afl8", choices=sorted(BENCHMARKS))
    ap.add_argument("--seed0", type=int, default=1, help="first seed (default 1: the public self-test seeds; an official grade uses a secret seed0)")
    ap.add_argument("--seeds", type=int, default=SEEDS, help="seeds, each from both ends (default %d = %d games)" % (SEEDS, 2 * SEEDS))
    ap.add_argument("--quick", action="store_true", help="20 seeds (40 games): a fast check, not a grade")
    ap.add_argument("--parallel", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--json", help="write the full report to this file")
    a = ap.parse_args(argv)
    if a.quick:
        a.seeds = 20

    game = a.game; g = get_game(game); chal = os.path.abspath(a.bot); blabel, bench = BENCHMARKS[game]
    full = a.seeds == SEEDS
    report = {"game": game, "engine_version": engine_version(g), "seconds": SECONDS, "bot": os.path.basename(chal),
              "bot_hash": code_hash(chal, game), "benchmark": blabel, "benchmark_hash": code_hash(bench, game),
              "seed0": a.seed0, "seeds": a.seeds, "full_grade": full, "failures": []}
    fail = report["failures"]
    print("%s | engine v%s | %d s games | bot %s (%s) | benchmark %s" % (game, engine_version(g), SECONDS, report["bot"], report["bot_hash"][:12], blabel))

    # 1. CHECK: it loads, and it does not ask for the game hook
    probe = load_bot(chal, "A", g.make_rules(SECONDS), a.seed0, game).inner
    if hasattr(probe, "observe_game"):
        fail.append("the bot defines observe_game (access to the true game object is not allowed)")

    # 3. MATCH against the benchmark
    print("Match: %d games against %s" % (2 * a.seeds, blabel))
    rows = run(jobs_for(game, chal, bench, a.seed0, a.seeds), a.parallel)

    # 1. CHECK (continued): replay the first seeds in this process, and compare
    replay = Serial().map(play, jobs_for(game, chal, bench, a.seed0, min(DETERMINISM_SEEDS, a.seeds)))
    first = {(r["seed"], r["side"]): (r["for"], r["against"]) for r in rows}
    diff = [r for r in replay if first.get((r["seed"], r["side"])) != (r["for"], r["against"])]
    if diff:
        fail.append("not deterministic: seed %d (team %s) gave a different game when it was played again" % (diff[0]["seed"], diff[0]["side"]))

    m = summary(rows); m["beats_benchmark"] = m["win_rate"] >= PASS_SCORE
    report["match"] = m

    # 2. CLOCK and errors
    calls = sum(r["calls"] for r in rows); total = sum(r["total_s"] for r in rows); worst = max(r["worst_s"] for r in rows)
    errors = sum(r["errors"] for r in rows)
    report["clock"] = {"decisions": calls, "mean_ms": 1000 * total / max(calls, 1), "max_ms": 1000 * worst}
    report["errors"] = errors
    if errors:
        e = next(r for r in rows if r["errors"])
        fail.append("%d errors (a bot error is a lost turn), first: %s" % (errors, e["first_error"]))
    if report["clock"]["mean_ms"] > MEAN_MS:
        fail.append("too slow: mean %.1f ms per decision (limit %.0f ms)" % (report["clock"]["mean_ms"], MEAN_MS))
    if report["clock"]["max_ms"] > MAX_MS:
        fail.append("too slow: one decision took %.0f ms (limit %.0f ms)" % (report["clock"]["max_ms"], MAX_MS))
    report["valid"] = not fail

    # the report
    print()
    print("MATCH against %s: %d games, won %d, lost %d, drawn %d, points %d to %d"
          % (blabel, m["games"], m["won"], m["lost"], m["drawn"], m["points_for"], m["points_against"]))
    print("  win rate  %.1f %%   (95 %% interval %.1f to %.1f %%)" % (100 * m["win_rate"], 100 * m["low95"], 100 * m["high95"]))
    print("  Elo       %s   (95 %% interval %s to %s; %s = 0)" % (elo_text(m["elo"]), elo_text(m["elo_low95"]), elo_text(m["elo_high95"]), blabel))
    print("  beats the benchmark (win rate %.0f %% or more): %s" % (100 * PASS_SCORE, "YES" if m["beats_benchmark"] else "no"))
    print("CLOCK: %d decisions, mean %.1f ms, longest %.0f ms (limits %.0f ms and %.0f ms)" % (calls, report["clock"]["mean_ms"], report["clock"]["max_ms"], MEAN_MS, MAX_MS))
    print("ERRORS: %d" % errors)
    print()
    if fail:
        print("INVALID:"); [print("  - " + x) for x in fail]
    elif not full:
        print("Valid. This was not a full grade (a full grade is %d seeds, %d games)." % (SEEDS, 2 * SEEDS))
    else:
        print("Valid. Full grade, seed0 = %d." % a.seed0)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print("Report: %s" % a.json)
    return 0 if not fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
