"""The oval: an ellipse centred on the ground with its pointed ends cut flat at the goal lines.

The ellipse semi-axes are chosen so that its half-width at the goal lines (x = 0 and
x = length) equals the behind-post half-width: the flat goal line is exactly the span between
the behind posts, and anything crossing the curved boundary is out of bounds. Also the
hallmark lines for the renderer (centre circle, centre square, arcs, goal squares).
"""
from __future__ import annotations

import math

import numpy as np

from .config import Rules


class Oval:
    def __init__(self, r: Rules):
        self.r = r
        self.cx, self.cy = r.length / 2, 0.0
        self.b = r.width / 2
        # half-width at the goal line must equal the behind-post half-width
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

    def crossing(self, p0, p1):
        """Point where the segment p0 -> p1 leaves the oval (p0 inside, p1 outside), by bisection."""
        lo, hi = 0.0, 1.0
        p0 = np.asarray(p0, float); p1 = np.asarray(p1, float)
        for _ in range(30):
            mid = 0.5 * (lo + hi)
            if self.inside(p0 + mid * (p1 - p0)):
                lo = mid
            else:
                hi = mid
        return p0 + lo * (p1 - p0)

    def inward(self, p):
        v = np.array([self.cx, self.cy]) - np.asarray(p, float)
        n = np.linalg.norm(v)
        return v / n if n > 1e-9 else np.array([1.0, 0.0])

    def outline(self, n=200):
        t = np.linspace(0, 2 * math.pi, n)
        x = self.cx + self.a * np.cos(t); y = self.b * np.sin(t)
        x = np.clip(x, 0.0, self.r.length)
        y = np.array([min(max(yy, -self.half_width(xx)), self.half_width(xx)) for xx, yy in zip(x, y)])
        return x, y

    def lines(self) -> dict:
        r = self.r
        L = r.length
        sq = r.goal_square_depth; gw = r.goal_half_width
        return {"centre_circle": (self.cx, 0.0, r.centre_circle_radius),
                "centre_square": (self.cx - r.centre_square / 2, -r.centre_square / 2, r.centre_square, r.centre_square),
                "arcs": [(0.0, r.arc_radius), (L, r.arc_radius)],
                "goal_squares": [(0.0, -gw, sq, 2 * gw), (L - sq, -gw, sq, 2 * gw)]}


def goal_line_crossing(p0, p1, goal_x):
    """y at which the segment p0 -> p1 crosses the vertical line x = goal_x going outward, or None."""
    x0, x1 = p0[0], p1[0]
    if goal_x > 0:
        hit = x0 < goal_x <= x1 or (x0 <= goal_x and x1 > goal_x)
    else:
        hit = x0 > goal_x >= x1 or (x0 >= goal_x and x1 < goal_x)
    if not hit or abs(x1 - x0) < 1e-12:
        return None
    t = (goal_x - x0) / (x1 - x0)
    return float(p0[1] + t * (p1[1] - p0[1]))


def score_of(y, r: Rules):
    if abs(y) < r.goal_half_width:
        return "goal"
    if abs(y) < r.behind_half_width:
        return "behind"
    return "out"
