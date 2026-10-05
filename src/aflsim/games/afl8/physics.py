"""Movement, pressure and ball-flight mechanics. Pure functions of the rules and the state."""
from __future__ import annotations

import math

import numpy as np

from .config import Rules


def move_player(pos, vel, target, top_speed, accel, dt, rules: Rules, oval=None):
    """Acceleration-limited pursuit of a standing target (None = decelerate to a stop). Returns (pos, vel).
    Players are kept inside the oval (or the bounding rectangle if no oval is given)."""
    if target is None:
        desired = np.zeros(2)
    else:
        d = target - pos
        dist = np.linalg.norm(d)
        want = min(top_speed, math.sqrt(2 * accel * max(dist - 0.3, 0.0)) if dist > 0.3 else 0.0)
        desired = d / dist * want if dist > 1e-6 else np.zeros(2)
    dv = desired - vel
    n = np.linalg.norm(dv)
    if n > accel * dt:
        dv = dv / n * accel * dt
    vel = vel + dv
    pos = pos + vel * dt
    if oval is not None:
        if not oval.inside(pos):
            clipped = oval.clip(pos)
            vel = np.where(np.abs(clipped - pos) > 1e-9, 0.0, vel)
            pos = clipped
        return pos, vel
    lo = np.array([0.0, -rules.width / 2]); hi = np.array([rules.length, rules.width / 2])
    clipped = np.clip(pos, lo, hi)
    vel = np.where(clipped != pos, 0.0, vel)
    return clipped, vel


def pressure_at(pos, opponents_pos, rules: Rules) -> float:
    if len(opponents_pos) == 0:
        return 0.0
    d = np.linalg.norm(np.asarray(opponents_pos) - pos, axis=1)
    return float(min(np.exp(-(d / rules.pressure_scale) ** 2).sum(), rules.pressure_cap))


def disposal_error_sigma(base, dist, dist_scale, accuracy, pressure, speed_frac, power, power_gain, rules: Rules, angular=0.0) -> float:
    """Landing error (sigma per axis, m). Kicks: angular error (base + angular x distance); handballs: base x (1 + d / scale).
    Both grow with pressure and running speed and shrink with the accuracy attribute (factor 0.5 + 0.5 x accuracy)."""
    scale = (1 + dist / dist_scale) if dist_scale > 0 else 1.0
    return (base + angular * dist) * scale * (1 + power_gain * power) * (1 + rules.pressure_error_gain * pressure) * (1 + rules.moving_error_gain * speed_frac) / (0.5 + 0.5 * max(accuracy, 0.0))


class Flight:
    def __init__(self, origin, landing, duration, kind, kicker, t0, requested_distance):
        self.origin = np.array(origin, float); self.landing = np.array(landing, float)
        self.duration = max(duration, 0.05); self.kind = kind; self.kicker = kicker; self.t0 = t0
        self.distance = float(np.linalg.norm(self.landing - self.origin))
        self.requested_distance = requested_distance
        self.max_height = 1.0 + 0.16 * self.distance if kind == "kick" else 1.6

    def frac(self, t):
        return min(max((t - self.t0) / self.duration, 0.0), 1.0)

    def position(self, t):
        return self.origin + (self.landing - self.origin) * self.frac(t)

    def height(self, t):
        f = self.frac(t)
        return 4 * self.max_height * f * (1 - f)

    def ground_velocity(self):
        return (self.landing - self.origin) / self.duration

    def landed(self, t):
        return t >= self.t0 + self.duration

    def contestable(self, t, rules: Rules):
        return self.height(t) <= rules.kick_catch_height


def launch(rng, rules: Rules, origin, target, kind, power, player, pressure, t0, speed_frac):
    d = np.asarray(target, float) - origin
    dist_req = float(np.linalg.norm(d))
    direction = d / dist_req if dist_req > 1e-6 else np.array([1.0, 0.0])
    if kind == "kick":
        reach = player.kick_range(rules) * power                                  # what this power carries
        bomb_max = reach * rules.kick_bomb_scale
        dist = min(dist_req, bomb_max)
        excess = max(dist - reach, 0.0) / max(reach * (rules.kick_bomb_scale - 1.0), 1e-6)   # 0 within range .. 1 a full bomb
        sigma = disposal_error_sigma(rules.kick_base_error, dist, rules.kick_distance_error_scale, player.attrs["kick_accuracy"], pressure, speed_frac,
                                     power, rules.kick_power_error_gain, rules, angular=rules.kick_angular_error) * (1.0 + rules.kick_bomb_error_gain * excess ** 2)
        shorten = max(1.0 - rules.pressure_distance_loss * pressure, 0.3)           # a rushed kick loses distance
        cap = max(reach, dist) * shorten; dist *= shorten                        # the furthest this kick can possibly land
        duration = rules.kick_flight_base + dist / rules.kick_ground_speed
    else:
        dist = min(dist_req, player.handball_range(rules) * power)
        sigma = disposal_error_sigma(rules.handball_base_error, dist, rules.handball_distance_error_scale, player.attrs["handball_accuracy"], pressure, speed_frac,
                                     power, 0.3, rules)
        duration = 0.15 + dist / rules.handball_speed
        cap = None
    aim = origin + direction * dist
    err = rng.normal(size=2) * sigma
    if cap is not None:                                                             # scatter can drop a kick short or wide, never carry it past the kicker's reach
        along = float(err @ direction); across = err - along * direction
        if along > cap - dist:                                                       # would carry past the reach: it drops short instead (folded)
            along = 2.0 * (cap - dist) - along
        along = max(along, 3.0 - dist)                                                 # ... and it always goes at least 3 m forward
        off = along * direction + across; travelled = float(np.linalg.norm(direction * dist + off))
        if travelled > cap:                                                          # the same fold for the total distance, wide kicks included
            fold = max(2.0 * cap - travelled, 3.0) / travelled
            off = (direction * dist + off) * fold - direction * dist
        landing = aim + off
    else:
        landing = aim + err
    return Flight(origin, landing, duration, kind, player.pid, t0, dist), sigma
