"""All rules and physical constants of the simplified game, in one place.

Everything here is a law of the game, a physical constant or a capability range. Nothing
here is a strategy. Distances in metres, times in seconds, speeds in m/s.

The ground is an oval (see ground.py) with a goal at each end: team A scores at x = length
and defends x = 0; team B scores at x = 0 and defends x = length.
"""
from __future__ import annotations


from dataclasses import dataclass


@dataclass(frozen=True)
class Rules:
    # ---- ground and goals
    length: float = 140.0                     # goal line to goal line (a suburban oval; four_a_side() gives the 90 x 55 m training ground)
    width: float = 100.0                      # across the centre
    goal_half_width: float = 3.2              # between the goal posts (6.4 m)
    behind_half_width: float = 9.6            # between the behind posts (19.2 m) = the flat goal line of the oval
    goal_points: int = 6
    behind_points: int = 1
    goal_square_depth: float = 9.0            # kick-ins are taken from the top of the goal square
    centre_square: float = 50.0               # cosmetic lines (drawn in the replay)
    centre_circle_radius: float = 3.0
    arc_radius: float = 50.0

    # ---- time
    physics_dt: float = 0.05
    decision_interval: float = 1.0
    episode_seconds: float = 240.0             # full time: 4-minute games by default (pass Rules(episode_seconds=...) for others) (end_on="time"); a goal ends the episode earlier if end_on="goal"
    replay_sample_dt: float = 0.1

    # ---- teams and start
    n_per_team: int = 8
    lineup: tuple = ("midfielder", "midfielder", "defender", "defender", "defender", "forward", "forward", "forward")   # role of player i of each team
    ability_bonus: tuple = (0.0, 0.0)         # added to every sampled attribute of team A / team B (clipped to 1): handicap experiments
    min_possession_seconds: float = 0.4       # a disposal cannot leave before the ball has been held this long (gathering time; tackles can land)

    # ---- ball flight
    kick_range_min_frac: float = 0.22          # full-power kick range = length x (min + kick_power x (max - min)): 31-56 m on the 140 m ground, scaled with it
    kick_range_max_frac: float = 0.40
    kick_bomb_scale: float = 1.3               # a target beyond range may be attempted up to this x range (a "bomb") ...
    kick_bomb_error_gain: float = 9.0          # ... with the landing sigma x (1 + gain x (how far into the bomb zone)^2): a full bomb is about 1/10 as accurate
    pressure_distance_loss: float = 0.12       # a kick loses this fraction of its distance per unit of pressure (pressure tops out at 2); scatter never adds distance
    kick_flight_base: float = 0.8
    kick_ground_speed: float = 22.0
    kick_catch_height: float = 2.5
    kick_base_error: float = 0.3               # landing error sigma = (base + angular x distance) x pressure / running terms / accuracy
    kick_angular_error: float = 0.085          # m of sigma per m of kick: ~5 degrees; 84 / 68 / 55 / 46 % goals from 20 / 30 / 40 / 50 m straight in front
    kick_distance_error_scale: float = 0.0     # 0 = no extra (1 + d/scale) term
    kick_power_error_gain: float = 0.0
    pressure_error_gain: float = 0.5           # disposal error multiplier is (1 + gain x pressure)
    handball_max_distance_scale: float = 22.0
    handball_min_distance_scale: float = 12.0
    handball_speed: float = 11.0
    handball_base_error: float = 0.15
    handball_distance_error_scale: float = 12.0
    moving_error_gain: float = 0.4
    roll_fraction: float = 0.35
    roll_decay: float = 1.8

    # ---- contests
    mark_min_kick_distance: float = 15.0
    mark_radius: float = 3.0
    mark_base: float = 0.85                   # mark weight = (mark_base + mark_skill_gain x marking_skill) x (1 - mark_distance_gain x d / mark_radius)
    mark_skill_gain: float = 0.15             #               / (1 + mark_pressure_gain x pressure^2): ~95 % uncontested, ~60 % with an opponent at 1 m
    mark_distance_gain: float = 0.35
    mark_pressure_gain: float = 0.5
    possession_radius: float = 2.0
    gather_rate: float = 6.0                  # gather hazard per second at the ball for a stationary player x (0.5 + 0.5 ground_ball_skill)
    gather_speed_penalty: float = 0.75        # divided by (1 + penalty x running fraction): sprinting through the ball is harder, not hopeless
    loose_ball_reflex_radius: float = 4.0     # auto_contest: any player this close to a loose ball goes for it, whatever their order
    flight_reflex_radius: float = 8.0         # auto_contest: any player this close to where a kick will land runs to it and contests, whatever their order
    tackle_radius: float = 2.0
    tackle_rate: float = 1.2
    holding_the_ball_seconds: float = 1.0     # prior opportunity: held this long, or run prior_opportunity_m with it; a tackle then earns a free kick
    prior_opportunity_m: float = 5.0

    # ---- set plays (marks, free kicks, kick-ins)
    set_play_seconds: float = 6.0             # the taker may hold the ball this long before play on is called
    set_play_retreat: float = 5.0             # the taker goes back this far behind the mark
    man_on_mark_radius: float = 15.0          # a set play (with a man on the mark) only when an opponent is this close; otherwise the player just plays on
    shot_target_push: float = 6.0             # a shot aimed within a few metres of the goal line is carried this far past it (so it cannot fall short of the line by design)
    protected_area: float = 8.0               # other opponents are kept at least this far from the taker during the set play
    protected_area_free_run: bool = True      # they still run freely around it: only the part of a run heading into it is stopped
                                              # (False = engine v1, where touching its edge zeroed a player's speed: they froze)
                                              # and a player heading for a spot inside it pulls up at its edge, slowing naturally
    contest_end_coast: bool = True            # when a contest ends (someone wins the ball), a player who was contesting it runs on a
                                              # couple of strides until their next order, instead of braking hard (False = engine v1)
    play_on_move: float = 1.0                 # moving this far from the retreat spot (or any MOVE / handball) is playing on
    kick_in_clearance: float = 15.0           # after a behind, opponents are moved at least this far from the kick-in taker

    # ---- pressure
    pressure_scale: float = 5.0
    pressure_cap: float = 2.0

    # ---- reflexes and running
    auto_contest: bool = True
    event_decisions: bool = True
    min_decision_gap: float = 0.3
    run_limit_m: float = 15.0
    # ---- energy: every player has energy 0..1 (starts full). Sprinting drains it, jogging or standing restores it,
    # and a tired player is slower: top speed and acceleration are scaled by (energy_speed_floor + (1 - floor) x energy).
    energy_sprint_fraction: float = 0.45     # effort above this fraction of base top speed drains energy, growing with the square of the excess ...
    energy_sprint_seconds: float = 6.0       # ... a full sprint empties a player in seconds x (0.5 + endurance): ~7 s for average endurance; a run (85 %) in ~2.5 x that (a player who never eases off is near empty by the last minute)
    energy_ramp_power: float = 2.0           # shape of the drain ramp between the threshold and a full sprint (2 = quadratic: a run costs ~40 % of a sprint)
    energy_recover_fraction: float = 0.45    # below this fraction (a jog, standing, holding a set play) energy comes back ...
    energy_recover_seconds: float = 60.0     # ... from empty to full in this long when standing still; a jog recovers at a bit under half that rate
    energy_speed_floor: float = 0.5          # an empty player runs at half pace; half energy = three-quarter pace
    pace_sprint: float = 1.0                 # MOVE pace multipliers on top speed: sprint / run (the default) / jog
    pace_run: float = 0.85
    pace_jog: float = 0.4                    # under the recovery line: a jog restores energy slowly, standing still restores it fastest
    speed_scale: float = 1.0                 # live play's arcade feel scales every player's top speed ...
    accel_scale: float = 1.0                 # ... and acceleration (1.0 everywhere else)
    bounce_base: float = 0.72                 # success = base + 0.45 x ground_ball_skill - speed penalty x speed fraction: ~80 % at full speed for an average player
    bounce_speed_penalty: float = 0.25
    spoil_skill_factor: float = 1.15          # a spoil is easier than a mark: fists beat hands
    throw_in_distance: float = 8.0

    # ---- endings
    end_on: str = "time"                      # "time": play restarts with a centre ball-up after a goal until full time; "goal": a goal ends the episode; "score": any score ends it

    @property
    def n_players(self) -> int:
        return 2 * self.n_per_team

    def __post_init__(self):
        assert len(self.lineup) == self.n_per_team, "lineup must name a role for every player"
        assert all(r.partition(":")[0] in ROLE_PROFILES for r in self.lineup), "unknown role in lineup"   # "line" or "line:archetype"

    @classmethod
    def four_a_side(cls, **overrides) -> "Rules":
        """The small training-ground game: 4 a side on a 90 x 55 m oval (tests, scripted scenarios, cheap runs)."""
        base = dict(length=90.0, width=55.0, centre_square=25.0, arc_radius=30.0, n_per_team=4, lineup=("midfielder", "midfielder", "defender", "forward"),
                    kick_range_min_frac=35.0 / 90.0, kick_range_max_frac=65.0 / 90.0)          # full-size kicks (35-65 m) on the small ground
        base.update(overrides)
        return cls(**base)

    @property
    def kick_min_distance_scale(self) -> float:
        """Full-power range of a kick_power 0 player, in metres (scales with the ground)."""
        return self.length * self.kick_range_min_frac

    @property
    def kick_max_distance_scale(self) -> float:
        return self.length * self.kick_range_max_frac

    @classmethod
    def from_log(cls, saved: dict) -> "Rules":
        """The rules a stored game was played under. A rule added since it was recorded takes its OLD behaviour
        (LEGACY), so old games replay exactly as they were played."""
        known = {k: (tuple(v) if isinstance(v, list) else v) for k, v in saved.items() if k in cls.__dataclass_fields__}
        return cls(**{**{k: v for k, v in LEGACY.items() if k not in known}, **known})

    def goal_x(self, team: str) -> float:
        """The goal line a team scores in."""
        return self.length if team == "A" else 0.0

    def own_goal_x(self, team: str) -> float:
        return 0.0 if team == "A" else self.length


ATTRIBUTE_NAMES = ("speed", "acceleration", "endurance", "kick_power", "kick_accuracy", "handball_power", "handball_accuracy",
                   "marking_skill", "ground_ball_skill", "tackling_skill")

TOP_SPEED_MIN, TOP_SPEED_MAX = 6.5, 9.0

# Role profiles: the mean of each attribute for a player of that role; individuals are drawn around the mean
# (sd ROLE_SPREAD, clipped to [0.35, 1]). Capabilities only: nothing here says where a player should play.
ROLE_PROFILES = {
    "midfielder": dict(speed=0.80, acceleration=0.80, endurance=0.85, kick_power=0.60, kick_accuracy=0.62, handball_power=0.75, handball_accuracy=0.82,
                       marking_skill=0.55, ground_ball_skill=0.85, tackling_skill=0.75),
    "forward":    dict(speed=0.58, acceleration=0.60, endurance=0.55, kick_power=0.88, kick_accuracy=0.86, handball_power=0.60, handball_accuracy=0.62,
                       marking_skill=0.90, ground_ball_skill=0.60, tackling_skill=0.50),
    "defender":   dict(speed=0.66, acceleration=0.66, endurance=0.65, kick_power=0.76, kick_accuracy=0.62, handball_power=0.62, handball_accuracy=0.68,
                       marking_skill=0.82, ground_ball_skill=0.66, tackling_skill=0.86),
}
ROLE_SPREAD = 0.10
ACCEL_MIN, ACCEL_MAX = 2.5, 5.0


# What a rule added after engine v1 meant before it existed (used for games recorded without it: see Rules.from_log).
LEGACY = {"protected_area_free_run": False, "contest_end_coast": False}
