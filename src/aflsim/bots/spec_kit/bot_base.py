"""Everything your bot needs besides numpy: the Action order, the game's numbers (Rules), the ground's geometry (Oval)
and BotBase, a base class with geometry helpers and state bookkeeping (no football decisions).

Your bot file does `from bot_base import Action, BotBase` (and, if you want them, Rules, Oval, TeamController).
The tournament runs your file unchanged against the league's own copy of this module, which behaves the same, so
import only those five names from it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_ACTION_TYPES = ("MOVE", "KICK", "HANDBALL", "ATTEMPT_POSSESSION", "ATTEMPT_MARK", "SPOIL", "TACKLE", "HOLD")
_PACES = ("sprint", "run", "jog")
_RULES = {}   # the game's numbers: filled in when the kit is built (the same values RULES.md describes)


@dataclass
class Action:
    player: str
    kind: str
    target: list | None = None          # [x, y] for MOVE / KICK / HANDBALL
    target_player: str | None = None    # KICK / HANDBALL to a teammate
    opponent: str | None = None         # TACKLE
    power: float = 1.0                  # KICK / HANDBALL, 0..1
    pace: str = "run"                   # MOVE: sprint | run | jog


class Rules:
    """The game's numbers (ground size, kick ranges, speeds...): read them as attributes, e.g. rules.length."""

    def __init__(self, **overrides):
        for k, v in dict(_RULES, **overrides).items():
            setattr(self, k, v)

    def goal_x(self, team: str) -> float:
        """The goal line a team scores in."""
        return self.length if team == "A" else 0.0

    def own_goal_x(self, team: str) -> float:
        return 0.0 if team == "A" else self.length


class Oval:
    """The ground: an ellipse with its ends cut flat at the goal lines (x = 0 and x = length)."""

    def __init__(self, r: Rules):
        self.r = r
        self.cx, self.cy = r.length / 2, 0.0
        self.b = r.width / 2
        self.a = (r.length / 2) / math.sqrt(1.0 - (r.behind_half_width / self.b) ** 2)

    def inside(self, p) -> bool:
        x, y = float(p[0]), float(p[1])
        if x < 0.0 or x > self.r.length:
            return False
        return ((x - self.cx) / self.a) ** 2 + (y / self.b) ** 2 <= 1.0 + 1e-9

    def half_width(self, x) -> float:
        u = (x - self.cx) / self.a
        return self.b * math.sqrt(max(1.0 - u * u, 0.0))

    def clip(self, p):
        """Nearest-ish point inside: clamp x to the goal lines, then y to the ellipse half-width."""
        x = min(max(float(p[0]), 0.0), self.r.length)
        hw = self.half_width(x)
        return np.array([x, min(max(float(p[1]), -hw), hw)])


class TeamController:
    name = "base"

    def __init__(self, team: str):
        self.team = team            # "A" or "B"

    def choose_actions(self, game_state: dict, problems: list[str]) -> tuple[str, list]:
        """Return (intent, actions). `problems` lists the invalid actions from the previous turn."""
        raise NotImplementedError

    def team_ids(self, state):
        return [p["id"] for p in state["team_" + self.team]]

    def opponent_ids(self, state):
        return [p["id"] for p in state["team_" + ("B" if self.team == "A" else "A")]]


class BotBase(TeamController):
    def __init__(self, team, rules: Rules | None = None, seed: int = 0):
        super().__init__(team)
        rules = rules if rules is not None else Rules()
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
