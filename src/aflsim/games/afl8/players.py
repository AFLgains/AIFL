"""Players: attributes and per-player dynamic state."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import ACCEL_MAX, ACCEL_MIN, ATTRIBUTE_NAMES, ROLE_PROFILES, ROLE_SPREAD, TOP_SPEED_MAX, TOP_SPEED_MIN, Rules


def sample_attributes(rng: np.random.Generator, role: str | None = None, lo=0.35, hi=1.0, profiles: dict | None = None) -> dict:
    """Attributes in [lo, hi]. With a role, each attribute is drawn around the role profile's mean (sd ROLE_SPREAD);
    without one, uniformly. Players differ but none is hopeless."""
    if role is None:
        return {k: float(round(rng.uniform(lo, hi), 2)) for k in ATTRIBUTE_NAMES}
    prof = (profiles or ROLE_PROFILES)[role]
    return {k: float(round(min(hi, max(lo, rng.normal(prof[k], ROLE_SPREAD))), 2)) for k in ATTRIBUTE_NAMES}


@dataclass
class Player:
    pid: str                       # "A1".."A4", "B1".."B4"
    team: str                      # "A" or "B"
    attrs: dict
    role: str = "midfielder"           # midfielder | defender | forward: the line (formation, the bots' roles)
    archetype: str = ""                # afl18: ruck, inside_mid, tall_forward, key_back ... (the attribute profile); "" = the role's
    pos: np.ndarray = field(default_factory=lambda: np.zeros(2))
    vel: np.ndarray = field(default_factory=lambda: np.zeros(2))
    move_target: np.ndarray | None = None      # standing MOVE instruction
    # standing ball instructions for the current decision interval
    contest: bool = False                      # ATTEMPT_POSSESSION / ATTEMPT_MARK: go to the ball and contest it
    contest_kind: str = ""
    tackle_target: str | None = None           # TACKLE(opponent)
    spoil: bool = False                        # SPOIL: go to the landing point of a kick and punch it away
    pending_kick: dict | None = None           # KICK / HANDBALL to execute as soon as this player holds the ball
    # possession bookkeeping
    carried: float = 0.0                       # metres run with the ball since the last bounce / possession
    run_total: float = 0.0                     # metres run with the ball this possession (prior opportunity for holding the ball)
    held_since: float = -1.0
    protected_until: float = -1.0              # set play in progress until this clock
    mark_spot: np.ndarray | None = None
    frozen: bool = False                       # standing the mark during an opponent's set play
    energy: float = 1.0                        # 0..1: drained by sprinting, restored by jogging or standing
    pace: str = "run"                          # the MOVE pace: sprint | run | jog
    energy_floor: float = 0.5                  # copied from the rules: speed factor at zero energy
    speed_scale: float = 1.0                   # copied from the rules (live play's arcade feel)
    accel_scale: float = 1.0

    def __post_init__(self):
        self.attrs.setdefault("endurance", 0.7)

    @property
    def base_top_speed(self) -> float:
        return (TOP_SPEED_MIN + self.attrs["speed"] * (TOP_SPEED_MAX - TOP_SPEED_MIN)) * self.speed_scale

    @property
    def energy_factor(self) -> float:
        return self.energy_floor + (1.0 - self.energy_floor) * max(0.0, min(1.0, self.energy))

    @property
    def top_speed(self) -> float:
        """Effective top speed: the base scaled by energy."""
        return self.base_top_speed * self.energy_factor

    @property
    def accel(self) -> float:
        return (ACCEL_MIN + self.attrs["acceleration"] * (ACCEL_MAX - ACCEL_MIN)) * self.accel_scale * self.energy_factor

    def kick_range(self, rules: Rules) -> float:
        return rules.kick_min_distance_scale + self.attrs["kick_power"] * (rules.kick_max_distance_scale - rules.kick_min_distance_scale)

    def handball_range(self, rules: Rules) -> float:
        return rules.handball_min_distance_scale + self.attrs["handball_power"] * (rules.handball_max_distance_scale - rules.handball_min_distance_scale)

    def clear_ball_orders(self):
        self.contest = False; self.contest_kind = ""; self.tackle_target = None; self.pending_kick = None; self.spoil = False

    def speed_fraction(self) -> float:
        return float(np.linalg.norm(self.vel) / self.top_speed)

    def effort(self) -> float:
        """Speed as a fraction of the base (fresh) top speed: what drains energy."""
        return float(np.linalg.norm(self.vel) / self.base_top_speed)
