"""Test that your bot is sound before you submit it:   python check_bot.py my_bot.py

No match engine is needed: your bot is shown hundreds of real game situations recorded from league games (states.json:
the ball held, loose and in the air, set plays, kick-ins, from both ends of the ground) and every answer is checked.

  FAIL (fix before submitting)                          WARN (worth a look)
  - the file can't be loaded, or has no class Bot       - orders for the same player twice in one answer
  - imports anything but bot_base, numpy and the         - answers that change for the same situation and seed
    plain standard-library maths modules                - the ball carrier is never told to kick or handball
  - reads files, the network, or runs other programs    - slowish (over 20 ms per decision on average)
  - raises an exception                                 - marking / spoiling ordered when no kick is in the air
  - returns something other than (intent, [Action, ...])
  - orders a player who isn't on its team, an unknown action, a missing / non-numeric target, a bad pace or power,
    a pass to a player who isn't a teammate, a tackle on someone who isn't an opponent
  - changes the state it was given (both teams are shown the same state)
  - too slow: over 100 ms per decision on average, or over 2 s for any one decision

Passing this means your bot is sound: the organiser still plays it through the real engine when you submit.
"""
from __future__ import annotations

import argparse
import ast
import copy
import importlib.util
import json
import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bot_base  # noqa: E402

ALLOWED_MODULES = {"bot_base", "numpy", "math", "random", "collections", "itertools", "functools", "dataclasses", "typing",
                   "heapq", "bisect", "statistics", "enum", "copy", "__future__", "operator", "abc", "numbers", "fractions"}
FROM_BOT_BASE = {"Action", "BotBase", "Rules", "Oval", "TeamController"}      # what the league's bot_base also has
FORBIDDEN_CALLS = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "vars", "memoryview"}
MEAN_LIMIT, WORST_LIMIT, MEAN_WARN = 0.100, 2.0, 0.020


class Report:
    """Problems grouped by kind: each kind is reported once, with its first example and how often it happened."""

    def __init__(self):
        self.fails, self.warns = {}, {}

    @staticmethod
    def _add(book, msg, kind):
        kind = kind or msg
        if kind in book:
            book[kind][1] += 1
        else:
            book[kind] = [msg, 1]

    def fail(self, msg, kind=None):
        self._add(self.fails, msg, kind)

    def warn(self, msg, kind=None):
        self._add(self.warns, msg, kind)

    @staticmethod
    def lines(book):
        return [msg + ("   [%d times]" % n if n > 1 else "") for msg, n in book.values()]


# ------------------------------------------------------------------ 1. the file itself
def check_source(path, rep):
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, path)
    except SyntaxError as e:
        rep.fail("syntax error, line %s: %s" % (e.lineno, e.msg)); return False
    except OSError as e:
        rep.fail("can't read %s: %s" % (path, e)); return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_MODULES:
                    rep.fail("line %d: imports %r (allowed: bot_base, numpy, and %s)" % (node.lineno, a.name, ", ".join(sorted(ALLOWED_MODULES - {"bot_base", "numpy", "__future__"}))))
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if node.level:
                rep.fail("line %d: relative import (your bot is a single file)" % node.lineno)
            elif mod not in ALLOWED_MODULES:
                rep.fail("line %d: imports from %r (allowed: bot_base, numpy and plain maths / standard-library helpers)" % (node.lineno, node.module))
            elif mod == "bot_base":
                extra = [a.name for a in node.names if a.name not in FROM_BOT_BASE]
                if extra:
                    rep.fail("line %d: imports %s from bot_base: only %s exist in the tournament's copy" % (node.lineno, ", ".join(extra), ", ".join(sorted(FROM_BOT_BASE))))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            rep.fail("line %d: calls %s() (bots may not read files, run code from strings or ask for input)" % (node.lineno, node.func.id))
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr not in ("__init__", "__name__", "__class__", "__dict__"):
            rep.warn("line %d: uses %s (double-underscore tricks are best avoided)" % (node.lineno, node.attr))
    if not any(isinstance(n, ast.ClassDef) and n.name == "Bot" for n in tree.body):
        rep.fail("no top-level `class Bot` in the file")
    return not rep.fails


def load(path, rep):
    try:
        spec = importlib.util.spec_from_file_location("submitted_bot", path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    except Exception:                                                     # noqa: BLE001
        rep.fail("loading the file raised:\n" + indent(traceback.format_exc(limit=3))); return None
    cls = getattr(mod, "Bot", None)
    if cls is None or not callable(getattr(cls, "choose_actions", None)):
        rep.fail("class Bot has no choose_actions(self, state, problems) method"); return None
    return cls


def indent(s, n=6):
    return "\n".join(" " * n + line for line in s.rstrip().splitlines())


# ------------------------------------------------------------------ 2. every answer
def check_answer(out, state, team, rep, where):
    """Validate one (intent, actions) answer; returns the actions (or None if the shape is wrong)."""
    if not (isinstance(out, (tuple, list)) and len(out) == 2):
        rep.fail("%s: choose_actions must return (intent, [Action, ...]), got %s" % (where, type(out).__name__), "shape"); return None
    intent, acts = out
    if not isinstance(intent, str):
        rep.fail("%s: the intent (first value returned) must be a string, got %s" % (where, type(intent).__name__), "intent")
    if not isinstance(acts, (list, tuple)):
        rep.fail("%s: the actions (second value returned) must be a list, got %s" % (where, type(acts).__name__), "actions"); return None
    mine = {p["id"] for p in state["team_" + team]}; theirs = {p["id"] for p in state["team_" + ("B" if team == "A" else "A")]}
    seen = set()
    for a in acts:
        if not isinstance(a, bot_base.Action):
            rep.fail("%s: every order must be an Action (from bot_base), got %r" % (where, a), "not-action"); continue
        who = "%s: %s %s" % (where, a.player, a.kind)
        if a.player not in mine:
            rep.fail("%s: %r is not one of your players (%s)" % (where, a.player, ", ".join(sorted(mine))), "not-mine"); continue
        if a.player in seen:
            rep.warn("two orders for the same player in one answer (only the last one counts), e.g. %s" % who, "twice")
        seen.add(a.player)
        if a.kind not in bot_base._ACTION_TYPES:
            rep.fail("%s: unknown action %r (know: %s)" % (where, a.kind, ", ".join(bot_base._ACTION_TYPES)), "kind"); continue
        if a.target is not None:
            try:
                ok = len(a.target) == 2 and all(math.isfinite(float(v)) for v in a.target)
            except (TypeError, ValueError):
                ok = False
            if not ok:
                rep.fail("%s: target must be [x, y] numbers, got %r" % (who, a.target), "target")
        if a.kind == "MOVE":
            if a.target is None:
                rep.fail("%s: MOVE needs a target [x, y]" % who, "move-target")
            if a.pace not in bot_base._PACES:
                rep.fail("%s: pace must be one of %s, got %r" % (who, ", ".join(bot_base._PACES), a.pace), "pace")
        if a.kind in ("KICK", "HANDBALL"):
            if a.target is None and not a.target_player:
                rep.fail("%s: %s needs a target [x, y] or a target_player" % (who, a.kind), "disposal-target")
            if a.target_player and (a.target_player not in mine or a.target_player == a.player):
                rep.fail("%s: target_player %r must be a teammate" % (who, a.target_player), "teammate")
            try:
                pw = float(a.power)
                if not (math.isfinite(pw) and 0.0 <= pw <= 1.0):
                    rep.fail("%s: power must be between 0 and 1, got %r" % (who, a.power), "power")
            except (TypeError, ValueError):
                rep.fail("%s: power must be a number, got %r" % (who, a.power), "power")
        if a.kind == "TACKLE" and a.opponent not in theirs:
            rep.fail("%s: TACKLE needs opponent= one of %s, got %r" % (who, ", ".join(sorted(theirs)), a.opponent), "tackle")
        if a.kind in ("ATTEMPT_MARK", "SPOIL") and state["ball"].get("state") != "flight":
            rep.warn("%s ordered with no kick in the air (the player just goes to the ball), e.g. %s" % (a.kind, who), "no-flight-" + a.kind)
    return list(acts)


def plain(acts):
    """An answer as comparable text (NaN-safe: as a number NaN never equals itself)."""
    return repr([(a.player, a.kind, a.target if a.target is None else list(a.target), a.target_player, a.opponent, a.power, a.pace)
                 for a in acts if isinstance(a, bot_base.Action)])


def run_states(cls, states, rep, verbose=False):
    rules = bot_base.Rules(); stats = {}
    for team, seed in (("A", 7), ("B", 1007)):
        try:
            bot = cls(team, rules, seed)
        except Exception:                                                 # noqa: BLE001
            rep.fail("Bot(%r, rules, seed) raised:\n%s" % (team, indent(traceback.format_exc(limit=3)))); continue
        times = []; errors = 0; answers = []; disposals = holds = 0; kinds = {}
        for i, st in enumerate(states):
            where = "situation %d (%s, as team %s)" % (i, st["ball"].get("state"), team)
            before = copy.deepcopy(st)
            t0 = time.perf_counter()
            try:
                out = bot.choose_actions(st, [])
            except Exception:                                             # noqa: BLE001
                errors += 1
                rep.fail("%s: choose_actions raised:\n%s" % (where, indent(traceback.format_exc(limit=4))), "raised")
                answers.append(None); continue
            finally:
                times.append(time.perf_counter() - t0)
            if st != before:
                rep.fail("%s: your bot changed the state it was given (both teams see the same state: copy it before editing)" % where, "mutates")
                st.clear(); st.update(before)
            acts = check_answer(out, st, team, rep, where)
            answers.append(plain(acts) if acts is not None else None)
            holder = st["ball"].get("owner")
            if holder and holder[0] == team:
                holds += 1
                if any(a.player == holder and a.kind in ("KICK", "HANDBALL") for a in (acts or [])):
                    disposals += 1
            for a in acts or []:
                kinds[a.kind] = kinds.get(a.kind, 0) + 1
        mean = sum(times) / max(len(times), 1); worst = max(times) if times else 0.0
        if mean > MEAN_LIMIT or worst > WORST_LIMIT:
            rep.fail("as team %s: too slow (%.0f ms per decision on average, worst %.0f ms; limits %.0f ms and %.0f ms)" % (team, 1000 * mean, 1000 * worst, 1000 * MEAN_LIMIT, 1000 * WORST_LIMIT))
        elif mean > MEAN_WARN:
            rep.warn("as team %s: %.0f ms per decision on average (fine, but games will be slower to run)" % (team, 1000 * mean))
        if holds and not disposals:
            rep.warn("as team %s: in %d situations where your player had the ball you never told them to kick or handball (they will just run with it until caught)" % (team, holds))
        # the same seed and the same situations must give the same answers
        try:
            again = cls(team, rules, seed); same = True
            for st, ans in zip(states[:60], answers[:60]):
                out = again.choose_actions(copy.deepcopy(st), [])
                if ans is not None and isinstance(out, (tuple, list)) and len(out) == 2 and plain(out[1]) != ans:
                    same = False; break
            if not same:
                rep.warn("as team %s: a fresh bot with the same seed answered the same situation differently (use self.rng, not the global random, so games can be replayed)" % team)
        except Exception:                                                 # noqa: BLE001
            pass
        stats[team] = {"situations": len(states), "mean_ms": 1000 * mean, "worst_ms": 1000 * worst, "orders": kinds, "errors": errors,
                       "carrier": "%d of %d" % (disposals, holds)}
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="Test that a bot is sound before submitting it.")
    ap.add_argument("bot", help="your bot file, e.g. my_bot.py")
    ap.add_argument("--states", default=os.path.join(HERE, "states.json"), help="the recorded game situations to test against")
    a = ap.parse_args(argv)
    rep = Report()
    print("checking %s" % a.bot)
    cls = load(a.bot, rep) if check_source(a.bot, rep) else None
    stats = {}
    if cls is not None:
        with open(a.states, encoding="utf-8") as f:
            states = json.load(f)
        stats = run_states(cls, states, rep)
        for team, s in stats.items():
            orders = ", ".join("%s %d" % kv for kv in sorted(s["orders"].items(), key=lambda kv: -kv[1]))
            print("  as team %s: %d situations, %.1f ms per decision (worst %.0f ms), carrier disposed %s; orders given: %s"
                  % (team, s["situations"], s["mean_ms"], s["worst_ms"], s["carrier"], orders or "none"))
    for w in rep.lines(rep.warns):
        print("  WARN  " + w)
    for f in rep.lines(rep.fails):
        print("  FAIL  " + f)
    print("PASS: your bot is sound (the organiser will still play it through the real engine)" if not rep.fails else "FAIL: fix the problems above")
    return 0 if not rep.fails else 1


if __name__ == "__main__":
    sys.exit(main())
