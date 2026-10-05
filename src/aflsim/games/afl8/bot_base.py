"""Helpers for writing a bot: geometry and bookkeeping only, no football decisions.

Subclass BotBase and implement choose_actions(state, problems) -> (intent, [Action, ...]). See bot_template.py.
"""
from __future__ import annotations

import numpy as np

from .actions import Action  # noqa: F401  (re-exported for convenience)
from .config import Rules
from aflsim.bots.base import TeamController
from .ground import Oval


class BotBase(TeamController):
    def __init__(self, team, rules: Rules = Rules(), seed: int = 0):
        super().__init__(team)
        self.r = rules; self.oval = Oval(rules); self.rng = np.random.default_rng(seed)
        self.opp = "B" if team == "A" else "A"
        self.goal_x = rules.goal_x(team)          # the goal line I score in (140 for team A, 0 for team B)
        self.own_x = rules.own_goal_x(team)       # the goal line I defend
        self.dirn = 1.0 if self.goal_x > self.own_x else -1.0   # +1 if I attack towards larger x
        self.name = "bot"

    # ---- geometry
    def ahead(self, x, m):
        """x moved m metres towards the goal I attack."""
        return x + self.dirn * m

    def to_goal(self, pos):
        """Metres from pos to the centre of the goal I attack."""
        return float(np.hypot(self.goal_x - pos[0], pos[1]))

    def clip(self, x, y):
        """The nearest point inside the oval, as [x, y]."""
        p = self.oval.clip(np.array([x, y], float))
        return [float(p[0]), float(p[1])]

    def kick_range(self, p):
        """This player's full-power kick distance in metres, from its kick_power attribute."""
        return self.r.kick_min_distance_scale + p["attrs"]["kick_power"] * (self.r.kick_max_distance_scale - self.r.kick_min_distance_scale)

    @staticmethod
    def dist(a, b):
        return float(np.hypot(a[0] - b[0], a[1] - b[1]))

    # ---- state bookkeeping
    def split(self, state):
        """(mine, theirs, ball, holder) from the state, with players as dicts."""
        mine = state["team_" + self.team]; theirs = state["team_" + self.opp]
        ball = state["ball"]; holder = ball.get("owner")
        return mine, theirs, ball, holder

    def by_role(self, players):
        out = {"midfielder": [], "defender": [], "forward": []}
        for p in players:
            out.setdefault(p.get("role", "midfielder"), []).append(p)
        return out
