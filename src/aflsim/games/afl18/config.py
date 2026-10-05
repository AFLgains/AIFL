"""afl18's rules: afl8's laws and physics, unchanged, on a full-size ground with 18 a side and player archetypes.

Every rule and physical constant is afl8's (see aflsim.games.afl8.config); only the ground, the line-up and the
attribute profiles differ. Each team: 6 midfielders (1 ruck, 3 inside, 2 outside), 6 forwards (2 tall, 4 small) and
6 backs (2 key position, 4 running). A line-up entry is "line:archetype": the line (midfielder / forward /
defender) sets the kick-off formation and what the bots treat a player as; the archetype only sets the player's
attributes. Edit LINEUP (or pass Rules(lineup=...)) for other mixes.
"""
from __future__ import annotations

from dataclasses import dataclass

from aflsim.games.afl8.config import ACCEL_MAX, ACCEL_MIN, ATTRIBUTE_NAMES, LEGACY, ROLE_PROFILES, ROLE_SPREAD, TOP_SPEED_MAX, TOP_SPEED_MIN  # noqa: F401
from aflsim.games.afl8.config import Rules as Rules8

LINEUP = ("midfielder:ruck", "midfielder:inside_mid", "midfielder:inside_mid", "midfielder:inside_mid", "midfielder:outside_mid", "midfielder:outside_mid",
          "defender:key_back", "defender:key_back", "defender:running_back", "defender:running_back", "defender:running_back", "defender:running_back",
          "forward:tall_forward", "forward:tall_forward", "forward:small_forward", "forward:small_forward", "forward:small_forward", "forward:small_forward")


@dataclass(frozen=True)
class Rules(Rules8):
    length: float = 160.0                     # a full-size oval (the MCG is about 160 x 141)
    width: float = 130.0
    n_per_team: int = 18
    lineup: tuple = LINEUP


# Archetype profiles: the mean of each attribute (individuals are drawn around it, sd ROLE_SPREAD, clipped to [0.35, 1]).
# Capabilities only: nothing here says where a player should play.
ARCHETYPE_PROFILES = {
    "ruck":          dict(speed=0.55, acceleration=0.55, endurance=0.80, kick_power=0.70, kick_accuracy=0.55, handball_power=0.70, handball_accuracy=0.70,
                          marking_skill=0.94, ground_ball_skill=0.70, tackling_skill=0.66),
    "inside_mid":    dict(speed=0.72, acceleration=0.82, endurance=0.86, kick_power=0.58, kick_accuracy=0.58, handball_power=0.80, handball_accuracy=0.88,
                          marking_skill=0.55, ground_ball_skill=0.93, tackling_skill=0.88),
    "outside_mid":   dict(speed=0.88, acceleration=0.80, endurance=0.92, kick_power=0.70, kick_accuracy=0.82, handball_power=0.70, handball_accuracy=0.78,
                          marking_skill=0.62, ground_ball_skill=0.72, tackling_skill=0.62),
    "tall_forward":  dict(speed=0.58, acceleration=0.55, endurance=0.58, kick_power=0.92, kick_accuracy=0.86, handball_power=0.55, handball_accuracy=0.60,
                          marking_skill=0.95, ground_ball_skill=0.55, tackling_skill=0.45),
    "small_forward": dict(speed=0.86, acceleration=0.90, endurance=0.70, kick_power=0.68, kick_accuracy=0.84, handball_power=0.70, handball_accuracy=0.74,
                          marking_skill=0.60, ground_ball_skill=0.86, tackling_skill=0.80),
    "key_back":      dict(speed=0.60, acceleration=0.58, endurance=0.66, kick_power=0.82, kick_accuracy=0.62, handball_power=0.58, handball_accuracy=0.64,
                          marking_skill=0.93, ground_ball_skill=0.62, tackling_skill=0.82),
    "running_back":  dict(speed=0.85, acceleration=0.80, endurance=0.84, kick_power=0.80, kick_accuracy=0.78, handball_power=0.70, handball_accuracy=0.76,
                          marking_skill=0.66, ground_ball_skill=0.74, tackling_skill=0.74),
}
PROFILES = {**ROLE_PROFILES, **ARCHETYPE_PROFILES}
ARCHETYPES = tuple(ARCHETYPE_PROFILES)
