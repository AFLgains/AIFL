"""Deliberately bad or scripted play, for varied value-function data and for tests:

    random                      every player gets a random order each decision (ground-aware)
    idle                        nobody ever moves on purpose: every order is HOLD
    noisy:hold:0.4:<spec>       <spec>'s orders, but each player is frozen (HOLD) 40 % of the time
    noisy:random:0.3:<spec>     <spec>'s orders, but each player gets a random order 30 % of the time

A value model only knows the kinds of play it has seen; trained on the best bot against itself it misjudged teams
standing still or swarming. These add them.
"""
from __future__ import annotations

import numpy as np

from aflsim.bots.base import TeamController

from .actions import Action


def _random_action(pid, state, rules, rng, team):
    """One valid order for `pid`, drawn at random over the real ground."""
    L, half = rules.length, rules.width / 2
    holder = state["ball"].get("owner")
    tgt = [float(rng.uniform(0, L)), float(rng.uniform(-half, half))]
    if pid == holder:
        kind = "KICK" if rng.random() < 0.6 else "HANDBALL"
        return Action(pid, kind, target=tgt, power=float(rng.uniform(0.3, 1.0)))
    u = rng.random()
    if u < 0.45:
        return Action(pid, "MOVE", target=tgt, pace=str(rng.choice(["sprint", "run", "jog"])))
    if u < 0.70:
        return Action(pid, str(rng.choice(["ATTEMPT_POSSESSION", "ATTEMPT_MARK", "SPOIL"])))
    if u < 0.85 and holder and holder[0] != team:
        return Action(pid, "TACKLE", opponent=holder)
    return Action(pid, "HOLD")


class RandomBot(TeamController):
    name = "random"

    def __init__(self, team, rules, seed=0):
        super().__init__(team); self.rules = rules; self.rng = np.random.default_rng(seed)
        self.errors = []; self.last_problems = []

    def choose_actions(self, state, problems):
        return "random", [_random_action(pid, state, self.rules, self.rng, self.team) for pid in self.team_ids(state)]


class IdleBot(TeamController):
    name = "idle"

    def __init__(self, team, rules=None, seed=0):
        super().__init__(team); self.errors = []; self.last_problems = []

    def choose_actions(self, state, problems):
        return "idle", [Action(pid, "HOLD") for pid in self.team_ids(state)]


class NoisyBot(TeamController):
    """A real bot whose orders are corrupted player by player: frozen (mode 'hold') or replaced by a random order
    (mode 'random') with probability p. Players the inner bot left alone are corrupted too, so a 'hold' bot really
    does stand around."""

    def __init__(self, inner, mode, p, team, rules, seed=0):
        super().__init__(team); self.inner = inner; self.mode = mode; self.p = p; self.rules = rules
        self.rng = np.random.default_rng(seed + 7777)
        self.name = "noisy:%s:%.2f:%s" % (mode, p, getattr(inner, "name", "?"))
        self.errors = getattr(inner, "errors", []); self.last_problems = []

    def choose_actions(self, state, problems):
        intent, acts = self.inner.choose_actions(state, problems)
        by = {a.player: a for a in acts}
        out = []
        for pid in self.team_ids(state):
            if self.rng.random() < self.p:
                out.append(Action(pid, "HOLD") if self.mode == "hold" else _random_action(pid, state, self.rules, self.rng, self.team))
            elif pid in by:
                out.append(by[pid])
        return intent, out
