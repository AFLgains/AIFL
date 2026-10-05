"""Smoke-test a bot before it goes anywhere near a ladder: `afl check <spec>`.

It must: load as either team; give only valid orders (its own players, known actions, finite targets); play a short
game from each end against the plain rules bot without raising; and not be absurdly slow per decision.
"""
from __future__ import annotations

import math
import time

from aflsim.bots.base import TeamController
from aflsim.games import DEFAULT_GAME, get_game


class _Inspect(TeamController):
    """Passes the bot's orders through, recording anything invalid and the time each decision took."""

    def __init__(self, inner, action_types):
        super().__init__(inner.team); self.inner = inner; self.name = inner.name; self.bad = []; self.times = []; self.types = action_types

    def observe_game(self, game):
        getattr(self.inner, "observe_game", lambda g: None)(game)

    @property
    def errors(self):
        return self.inner.errors

    def choose_actions(self, state, problems):
        t = time.perf_counter()
        intent, acts = self.inner.choose_actions(state, problems)
        self.times.append(time.perf_counter() - t)
        mine = {p["id"] for p in state["team_" + self.team]}
        for a in acts:
            if a.player not in mine:
                self.bad.append("order for a player not on the team: %s" % a.player)
            if a.kind not in self.types:
                self.bad.append("unknown action %r" % a.kind)
            if a.target is not None and not all(math.isfinite(float(v)) for v in a.target):
                self.bad.append("non-finite target %r" % (a.target,))
        return intent, acts


def check_bot(spec: str, game: str = DEFAULT_GAME, seconds: float = 30.0) -> dict:
    from aflsim.bots.registry import bot_hash, canonical, load_bot
    from aflsim.engine import run_match
    g = get_game(game); lines = []; ok = True
    try:
        name = canonical(spec, game); h = bot_hash(spec, game)
        lines.append("bot %s  (hash %s)" % (name, h))
    except Exception as e:                                                 # noqa: BLE001
        return {"ok": False, "lines": ["cannot resolve %r: %s: %s" % (spec, type(e).__name__, e)]}
    from .. import bots as _b  # noqa: F401
    types = set(getattr(__import__("aflsim.games.%s.actions" % game, fromlist=["ACTION_TYPES"]), "ACTION_TYPES", ()))
    rules = g.make_rules(seconds)
    for end in ("A", "B"):
        other = "B" if end == "A" else "A"
        try:
            me = _Inspect(load_bot(spec, end, rules, 7 if end == "A" else 1007, game), types)
        except Exception as e:                                             # noqa: BLE001
            return {"ok": False, "lines": lines + ["FAIL: cannot load as team %s: %s: %s" % (end, type(e).__name__, e)]}
        opp = load_bot("zoo:rules", other, rules, 1007 if end == "A" else 7, game)
        ctl_a, ctl_b = (me, opp) if end == "A" else (opp, me)
        ep = run_match(g, ctl_a, ctl_b, rules, 7, record="none")
        st = ep["stats"]; mine, theirs = (st["score_A"], st["score_B"]) if end == "A" else (st["score_B"], st["score_A"])
        worst = max(me.times) if me.times else 0.0; mean = sum(me.times) / max(len(me.times), 1)
        lines.append("  as team %s: %d decisions, %d-%d v zoo:rules, %.1f ms/decision (worst %.0f ms), %d errors, %d invalid orders"
                     % (end, len(me.times), mine, theirs, 1000 * mean, 1000 * worst, len(me.errors), len(me.bad)))
        for e in me.errors[:3]:
            lines.append("    error: " + e)
        for b in sorted(set(me.bad))[:3]:
            lines.append("    invalid: " + b)
        if me.errors or me.bad:
            ok = False
        if mean > 2.0 and not spec.startswith(("search", "llm:")):
            lines.append("    WARNING: slow for a code bot (%.1f s per decision)" % mean)
    lines.append("PASS" if ok else "FAIL")
    return {"ok": ok, "lines": lines}
