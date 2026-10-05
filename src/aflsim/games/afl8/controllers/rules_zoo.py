"""A zoo of scripted teams, each built around one crude idea, to probe the game mechanics for exploits.

If one of these dumb plans beats the sensible rules team consistently, the mechanics are rewarding something
football does not. Each variant changes one thing about RulesController; all are free to run (no model calls).

    bomber    every possession is a full-power kick at the goal square; forwards spread between the ball and the goal
    camper    forwards camp in the goal square all game; everyone else bombs to them
    keepball  never risks a kick: handballs and short kicks to the least pressured teammate, shoots only inside 25 m
    press     everyone within reach hunts the carrier (4 tacklers, 5 to a contest), forwards press high
    boundary  kicks down the boundary line, forwards hold wide lanes
    runner    the carrier runs at goal (bouncing) until pressured or in range
    handball  handball chains only; kicks only to shoot inside 30 m
    spoiler   defenders always spoil, never mark; four to every contest
    stack     all eight players live within 20 m of the ball
    rusher    concedes rushed behinds to reset whenever pressured in its own 30 m
    lead      kicks only to leads at least 9 m from any opponent; forwards lead 35-45 m
    ontario   shoots at full power the moment the goal is in reach, else kicks to the corridor at full reach
    keeper    one defender lives in the goal square
    zone      modern footy: rolling zone without the ball, run / overlap / handball with it
    wall      all eight guard fixed spots across the defensive 65 m; clears down the boundary; no intent to score
"""
from __future__ import annotations

from ..actions import Action
from ..config import Rules
from .rules_ai import DefensiveRulesController, RulesController


class BomberBot(RulesController):
    name = "bomber"

    def __init__(self, team, rules=Rules(), seed=0, aggression=1.0):
        super().__init__(team, rules, seed, aggression); self.name = "bomber"

    def _dispose(self, me, mine, theirs, set_play):
        return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=1.0)

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        if we_have or not they_have:
            frac = 1.0 if abs(lane_y) < 1.0 else (0.6 if lane_y < 0 else 0.8)     # the centre forward in the square, the others up the corridor
            x = bpos[0] + (self.goal_x - bpos[0]) * frac
            x = self.own_x + self.dirn * min(self.dirn * (x - self.own_x), self.r.length - 8.0)
            return Action(p["id"], "MOVE", target=self.clip(x, lane_y * 0.4))
        return super()._forward(p, lane_y, bpos, we_have, they_have, holder, by_id, their_def)


class CamperBot(RulesController):
    name = "camper"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.5):
        super().__init__(team, rules, seed, aggression); self.name = "camper"

    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]; d_goal = self.to_goal(pos)
        if d_goal <= self.kick_range(me) * 0.95 and abs(pos[1]) < 22.0:
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=1.0)
        return Action(me["id"], "KICK", target=[self.goal_x - self.dirn * 6.0, 0.0], power=1.0)     # bomb to the square

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        return Action(p["id"], "MOVE", target=self.clip(self.goal_x - self.dirn * 7.0, lane_y * 0.3))


class KeepBallBot(RulesController):
    name = "keepball"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.0):
        super().__init__(team, rules, seed, aggression); self.name = "keepball"; self.shoot_range = 25.0

    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]; rng_k = self.kick_range(me); d_goal = self.to_goal(pos)
        if d_goal <= self.shoot_range and abs(pos[1]) < 15.0:
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=min(1.0, d_goal / rng_k + 0.15))
        mates = [q for q in mine if q["id"] != me["id"]]
        hb = [q for q in mates if 3.0 < self.dist(pos, q["pos"]) <= 12.0]
        if hb:
            q = min(hb, key=lambda q: q["pressure"])
            if q["pressure"] < 0.8:
                return Action(me["id"], "HANDBALL", target_player=q["id"], power=min(1.0, self.dist(pos, q["pos"]) / 16.0 + 0.25))
        ks = [q for q in mates if 15.0 <= self.dist(pos, q["pos"]) <= 28.0]
        if ks:
            q = min(ks, key=lambda q: q["pressure"] - 0.02 * self.dirn * (q["pos"][0] - pos[0]))
            tof = self.r.kick_flight_base + self.dist(pos, q["pos"]) / self.r.kick_ground_speed
            t = self.clip(q["pos"][0] + q["vel"][0] * tof, q["pos"][1] + q["vel"][1] * tof)
            return Action(me["id"], "KICK", target=t, power=min(1.0, self.dist(pos, t) / rng_k + 0.12))
        return Action(me["id"], "HOLD")

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        if we_have:                                                                 # come to the ball: a short option 18 m ahead
            carrier = by_id[holder]["pos"]
            return Action(p["id"], "MOVE", target=self.clip(self.ahead(carrier[0], 18.0), lane_y * 0.5))
        return super()._forward(p, lane_y, bpos, we_have, they_have, holder, by_id, their_def)

    def _midfielder(self, p, k, bpos, we_have, they_have, holder, by_id, mine, theirs, landing):
        if we_have:
            carrier = by_id[holder]["pos"]
            return Action(p["id"], "MOVE", target=self.clip(carrier[0] - self.dirn * (6.0 if k == 0 else 12.0), carrier[1] + (8.0 if k == 0 else -8.0)))
        return super()._midfielder(p, k, bpos, we_have, they_have, holder, by_id, mine, theirs, landing)


class PressBot(RulesController):
    name = "press"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.6):
        super().__init__(team, rules, seed, aggression); self.name = "press"; self.contest_n = 5; self.tackle_n = 4

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        if they_have and self.dist(p["pos"], bpos) < 35.0:
            return Action(p["id"], "TACKLE", opponent=holder)
        return super()._forward(p, lane_y, bpos, we_have, they_have, holder, by_id, their_def)

    def _defender(self, p, mark_id, bpos, we_have, they_have, holder, by_id):
        if they_have and self.dist(p["pos"], bpos) < 25.0:
            return Action(p["id"], "TACKLE", opponent=holder)
        return super()._defender(p, mark_id, bpos, we_have, they_have, holder, by_id)


class BoundaryBot(RulesController):
    name = "boundary"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.5):
        super().__init__(team, rules, seed, aggression); self.name = "boundary"

    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]; rng_k = self.kick_range(me); d_goal = self.to_goal(pos)
        if d_goal <= min(self.shoot_range, rng_k * 0.95) and abs(pos[1]) < 22.0:
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=min(1.0, d_goal / rng_k + 0.15))
        side = 1.0 if pos[1] >= 0 else -1.0
        t = self.clip(self.ahead(pos[0], min(rng_k * 0.85, 40.0)), side * 0.47 * self.r.width)
        return Action(me["id"], "KICK", target=t, power=min(1.0, self.dist(pos, t) / rng_k + 0.15))

    def _lanes(self, n):
        span = 0.44 * self.r.width
        return [(-span + 2 * span * i / max(n - 1, 1)) if n > 1 else 0.0 for i in range(n)]


class RunnerBot(RulesController):
    name = "runner"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.5):
        super().__init__(team, rules, seed, aggression); self.name = "runner"

    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]
        if self.to_goal(pos) > self.shoot_range and me["pressure"] < 0.9:
            return Action(me["id"], "MOVE", target=self.clip(self.ahead(pos[0], 30.0), pos[1] * 0.7))
        return super()._dispose(me, mine, theirs, set_play)


class HandballBot(RulesController):
    name = "handball"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.3):
        super().__init__(team, rules, seed, aggression); self.name = "handball"; self.shoot_range = 30.0

    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]; rng_k = self.kick_range(me); d_goal = self.to_goal(pos)
        if d_goal <= min(self.shoot_range, rng_k * 0.95) and abs(pos[1]) < 20.0:
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=min(1.0, d_goal / rng_k + 0.15))
        hb = [q for q in mine if q["id"] != me["id"] and 3.0 < self.dist(pos, q["pos"]) <= 16.0]
        if hb:
            q = max(hb, key=lambda q: self.dirn * (q["pos"][0] - pos[0]) - 6.0 * q["pressure"])
            return Action(me["id"], "HANDBALL", target_player=q["id"], power=min(1.0, self.dist(pos, q["pos"]) / 16.0 + 0.25))
        return super()._dispose(me, mine, theirs, set_play)

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        if we_have:
            carrier = by_id[holder]["pos"]
            return Action(p["id"], "MOVE", target=self.clip(self.ahead(carrier[0], 10.0), lane_y * 0.35))
        return super()._forward(p, lane_y, bpos, we_have, they_have, holder, by_id, their_def)


class SpoilerBot(DefensiveRulesController):
    name = "spoiler"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.4):
        super().__init__(team, rules, seed, aggression); self.name = "spoiler"; self.shoot_range = 40.0

    def choose_actions(self, state, problems):
        intent, acts = super().choose_actions(state, problems)
        flight = state["ball"].get("flight")
        if flight and flight.get("from", " ")[0] != self.team and flight.get("markable"):
            acts = [Action(a.player, "SPOIL") if a.kind == "ATTEMPT_MARK" else a for a in acts]
        return intent, acts


class StackBot(RulesController):
    name = "stack"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.5):
        super().__init__(team, rules, seed, aggression); self.name = "stack"; self.contest_n = 6; self.tackle_n = 3

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        return Action(p["id"], "MOVE", target=self.clip(self.ahead(bpos[0], 12.0), lane_y * 0.3))

    def _defender(self, p, mark_id, bpos, we_have, they_have, holder, by_id):
        return Action(p["id"], "MOVE", target=self.clip(bpos[0] - self.dirn * 10.0, p["pos"][1] * 0.3))


class RusherBot(DefensiveRulesController):
    """Defends by conceding: inside its own 30 m under any pressure it kicks the ball back through its own goal for a
    rushed behind (1 point, then a kick-in with a 15 m clearance). Probes whether deliberate rushed behinds pay."""
    name = "rusher"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.3):
        super().__init__(team, rules, seed, aggression); self.name = "rusher"

    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]
        if self.dirn * (pos[0] - self.own_x) < 30.0 and me["pressure"] > 0.3:
            return Action(me["id"], "KICK", target=[self.own_x - self.dirn * 6.0, 0.0], power=0.6)
        return super()._dispose(me, mine, theirs, set_play)


class LeadBot(RulesController):
    """Kicks only to a teammate leading into space at least 9 m from every opponent (outside the flight reflex);
    forwards lead long (35-45 m). Probes whether uncontested marking is too easy to manufacture."""
    name = "lead"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.4):
        super().__init__(team, rules, seed, aggression); self.name = "lead"

    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]; rng_k = self.kick_range(me); d_goal = self.to_goal(pos)
        if d_goal <= min(self.shoot_range, rng_k * 0.95) and abs(pos[1]) < 22.0:
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=min(1.0, d_goal / rng_k + 0.15))
        best, best_s = None, -1e9
        for q in mine:
            if q["id"] == me["id"]:
                continue
            d = self.dist(pos, q["pos"])
            if d < 15.0 or d > rng_k * 0.92:
                continue
            tof = self.r.kick_flight_base + d / self.r.kick_ground_speed
            proj = [q["pos"][0] + q["vel"][0] * tof, q["pos"][1] + q["vel"][1] * tof]
            space = min(self.dist(o["pos"], proj) for o in theirs)
            sc = 3.0 * min(space, 15.0) + self.dirn * (proj[0] - pos[0])
            if space >= 9.0 and sc > best_s:
                best, best_s, best_proj = q, sc, proj
        if best is not None:
            t = self.clip(*best_proj)
            return Action(me["id"], "KICK", target=t, power=min(1.0, self.dist(pos, t) / rng_k + 0.12))
        return super()._dispose(me, mine, theirs, set_play)

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        if we_have:
            carrier = by_id[holder]["pos"]
            lead = self.ahead(carrier[0], 35.0 + 10.0 * self.rng.random())
            lead = self.own_x + self.dirn * min(self.dirn * (lead - self.own_x), self.r.length - 10.0)
            return Action(p["id"], "MOVE", target=self.clip(lead, lane_y * (0.6 + 0.6 * self.rng.random())))
        return super()._forward(p, lane_y, bpos, we_have, they_have, holder, by_id, their_def)


class OntarioBot(RulesController):
    """The Season 1 premier's plan, made rule-aware: shoot the moment the goal is within reach (full power), otherwise
    kick to the corridor at full reach; forwards spread between the ball and the goal (0.6 / 0.8 / goal square)."""
    name = "ontario"

    def __init__(self, team, rules=Rules(), seed=0, aggression=1.0):
        super().__init__(team, rules, seed, aggression); self.name = "ontario"

    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]; rng_k = self.kick_range(me); d_goal = self.to_goal(pos)
        if d_goal <= rng_k and abs(pos[1]) < 30.0:
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=1.0)
        t = self.clip(self.ahead(pos[0], rng_k * 0.95), pos[1] * 0.3)
        return Action(me["id"], "KICK", target=t, power=1.0)

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        if we_have or not they_have:
            frac = 1.0 if abs(lane_y) < 1.0 else (0.6 if lane_y < 0 else 0.8)
            x = bpos[0] + (self.goal_x - bpos[0]) * frac
            x = self.own_x + self.dirn * min(self.dirn * (x - self.own_x), self.r.length - 8.0)
            return Action(p["id"], "MOVE", target=self.clip(x, lane_y * 0.4))
        return super()._forward(p, lane_y, bpos, we_have, they_have, holder, by_id, their_def)


class KeeperBot(RulesController):
    """One defender lives in the goal square as a keeper (spoils and marks on the line); the other two man-mark."""
    name = "keeper"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.5):
        super().__init__(team, rules, seed, aggression); self.name = "keeper"; self.keeper = None

    def _defender(self, p, mark_id, bpos, we_have, they_have, holder, by_id):
        if self.keeper is None:
            self.keeper = p["id"]
        if p["id"] == self.keeper:
            return Action(p["id"], "MOVE", target=self.clip(self.own_x + self.dirn * 6.0, bpos[1] * 0.2))
        return super()._defender(p, mark_id, bpos, we_have, they_have, holder, by_id)


class ZoneBot(RulesController):
    """Modern footy: a rolling zone without the ball, run-and-handball with it.

    Without the ball every player holds a spot in a shape that slides with the ball: the three defenders form a line
    28 m goal-side of the ball across the corridor, one midfielder attacks the ball and the other sits 12 m behind it,
    the forwards hold a line 35 m ahead of the ball and press only when the ball is in their attacking third.
    With the ball the carrier runs into space while unpressured (up to 12 m), then handballs to a teammate running
    past on the overlap, or kicks to a lead when nobody is; the two nearest teammates always offer the overlap run,
    the rest spread ahead in the shape. Shoots inside 40 m."""
    name = "zone"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.4):
        super().__init__(team, rules, seed, aggression); self.name = "zone"; self.contest_n = 2; self.tackle_n = 2

    # ------------------------------------------------------------------ with the ball
    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]; rng_k = self.kick_range(me); d_goal = self.to_goal(pos)
        if d_goal <= min(self.shoot_range, rng_k * 0.95) and abs(pos[1]) < 22.0:
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=min(1.0, d_goal / rng_k + 0.15))
        run_m = self._state_ball.get("run_this_possession_m", 0.0)
        # the overlap: a teammate within 12 m, moving forward faster than 3 m/s, less pressured than me
        over = [q for q in mine if q["id"] != me["id"] and 3.0 < self.dist(pos, q["pos"]) <= 12.0
                and self.dirn * q["vel"][0] > 3.0 and q["pressure"] < max(me["pressure"], 0.5)]
        if over and (me["pressure"] > 0.4 or run_m >= 10.0):
            q = max(over, key=lambda q: self.dirn * q["vel"][0] - 4.0 * q["pressure"])
            return Action(me["id"], "HANDBALL", target_player=q["id"], power=min(1.0, self.dist(pos, q["pos"]) / 16.0 + 0.3))
        if me["pressure"] < 0.6 and run_m < 12.0 and not set_play:
            side = 1.0 if pos[1] < 0 else -1.0                                        # angle towards the corridor
            return Action(me["id"], "MOVE", target=self.clip(self.ahead(pos[0], 14.0), pos[1] + side * 5.0))
        return super()._dispose(me, mine, theirs, set_play)

    def choose_actions(self, state, problems):
        self._state_ball = state["ball"]
        return super().choose_actions(state, problems)

    # ------------------------------------------------------------------ the shape
    def _shape_x(self, bpos, offset):
        x = bpos[0] + self.dirn * offset
        return self.own_x + self.dirn * float(min(max(self.dirn * (x - self.own_x), 8.0), self.r.length - 8.0))

    def _defender(self, p, mark_id, bpos, we_have, they_have, holder, by_id):
        idx = sorted(q for q in self._my_def_ids)                                  # a line: left, centre, right
        k = idx.index(p["id"]) if p["id"] in idx else 1
        lane = (-1, 0, 1)[k % 3] * 0.22 * self.r.width
        if we_have:
            return Action(p["id"], "MOVE", target=self.clip(self._shape_x(bpos, -24.0), lane * 0.8 + bpos[1] * 0.2))
        return Action(p["id"], "MOVE", target=self.clip(self._shape_x(bpos, -28.0), lane + bpos[1] * 0.3))

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        pos = p["pos"]
        if we_have:
            carrier = by_id[holder]["pos"]
            if self.dist(pos, carrier) < 22.0:                                       # close: run the overlap past the carrier
                side = 1.0 if pos[1] >= carrier[1] else -1.0
                return Action(p["id"], "MOVE", target=self.clip(self.ahead(carrier[0], 16.0), carrier[1] + side * 7.0))
            return Action(p["id"], "MOVE", target=self.clip(self._shape_x(bpos, 32.0), lane_y))
        if they_have and self.dirn * (bpos[0] - self.own_x) > self.r.length * 0.62 and self.dist(pos, bpos) < 30.0:
            return Action(p["id"], "TACKLE", opponent=holder)                        # press only in the attacking third
        return Action(p["id"], "MOVE", target=self.clip(self._shape_x(bpos, 35.0), lane_y))

    def _midfielder(self, p, k, bpos, we_have, they_have, holder, by_id, mine, theirs, landing):
        pos = p["pos"]
        if we_have:
            carrier = by_id[holder]["pos"]
            side = 1.0 if k == 0 else -1.0
            if self.dist(pos, carrier) < 20.0:                                       # overlap run past the carrier
                return Action(p["id"], "MOVE", target=self.clip(self.ahead(carrier[0], 14.0), carrier[1] + side * 8.0))
            return Action(p["id"], "MOVE", target=self.clip(carrier[0] + self.dirn * 6.0, carrier[1] + side * 12.0))
        if they_have:
            if k == 0:
                return Action(p["id"], "TACKLE", opponent=holder)
            return Action(p["id"], "MOVE", target=self.clip(self._shape_x(bpos, -12.0), bpos[1] * 0.5))
        target = landing or bpos
        return Action(p["id"], "ATTEMPT_POSSESSION") if self.dist(pos, target) < 25.0 else Action(p["id"], "MOVE", target=self.clip(target[0], target[1]))


class WallBot(RulesController):
    """Defence, defence, defence: all eight players guard spots in a zone covering the defensive 62 m (rows 8 / 24 /
    42 / 60 m from their own goal), so nothing can be bombed in from range. The grid slides sideways with the ball,
    and a player closes on an opponent standing in their space; otherwise nobody moves except to contest a kick coming
    down near them (spoil when an opponent is near the drop, mark when alone), pick up a loose ball within reach,
    tackle a carrier who comes to them, or take a clearing kick long down the line. No forward line, no intent to score."""
    name = "wall"

    def __init__(self, team, rules=Rules(), seed=0, aggression=0.0):
        super().__init__(team, rules, seed, aggression); self.name = "wall"
        w = self.r.width
        self.spots = [(8.0, -8.0), (8.0, 8.0), (24.0, -0.24 * w), (24.0, 0.0), (24.0, 0.24 * w), (42.0, -0.16 * w), (42.0, 0.16 * w), (60.0, 0.0)]
        self.contest_reach = 14.0; self.loose_reach = 10.0; self.tackle_reach = 8.0; self.guard_reach = 10.0

    def spot_of(self, k, ball_y):
        x, y = self.spots[k % len(self.spots)]
        return self.clip(self.own_x + self.dirn * x, y + 0.45 * ball_y)                    # the grid slides with the ball

    def choose_actions(self, state, problems):
        mine = state["team_" + self.team]; theirs = state["team_" + self.opp]
        ball = state["ball"]; bpos = ball["position"]; holder = ball["owner"]
        flight = ball.get("flight"); landing = flight["lands_at"] if flight else None
        we_have = holder is not None and holder[0] == self.team
        they_have = holder is not None and holder[0] == self.opp
        acts = []
        for k, p in enumerate(mine):
            pid = p["id"]; pos = p["pos"]; spot = self.spot_of(k, bpos[1])
            if we_have and holder == pid:
                acts.append(self._clear(p, mine, theirs)); continue
            if flight is not None and flight.get("from", " ")[0] != self.team and self.dist(pos, landing) < self.contest_reach:
                their_near = min(self.dist(q["pos"], landing) for q in theirs)
                if flight.get("markable"):
                    acts.append(Action(pid, "SPOIL" if their_near < 6.0 else "ATTEMPT_MARK"))
                else:
                    acts.append(Action(pid, "ATTEMPT_POSSESSION"))
                continue
            if ball["state"] == "loose" and self.dist(pos, bpos) < self.loose_reach:
                acts.append(Action(pid, "ATTEMPT_POSSESSION")); continue
            if they_have and self.dist(pos, bpos) < self.tackle_reach:
                acts.append(Action(pid, "TACKLE", opponent=holder)); continue
            intruder = min(theirs, key=lambda q: self.dist(q["pos"], spot))
            if self.dist(intruder["pos"], spot) < self.guard_reach:                        # someone is standing in my space: stand goal-side of them
                g = self.clip(intruder["pos"][0] + self.dirn * 2.5, intruder["pos"][1])
                acts.append(Action(pid, "MOVE", target=g)); continue
            acts.append(Action(pid, "MOVE", target=spot) if self.dist(pos, spot) > 1.0 else Action(pid, "HOLD"))
        return "wall: hold the zone", self._cover_instead_of_tackling(state, acts)

    def _clear(self, me, mine, theirs):
        pos = me["pos"]; rng_k = self.kick_range(me)
        side = 1.0 if pos[1] >= 0 else -1.0
        t = self.clip(self.ahead(pos[0], rng_k * 0.85), side * 0.30 * self.r.width)        # long down the line, safely inside the boundary
        return Action(me["id"], "KICK", target=t, power=1.0)


ZOO = {"rules": RulesController, "defence": DefensiveRulesController, "bomber": BomberBot, "camper": CamperBot, "keepball": KeepBallBot,
       "press": PressBot, "boundary": BoundaryBot, "runner": RunnerBot, "handball": HandballBot, "spoiler": SpoilerBot, "stack": StackBot, "rusher": RusherBot, "lead": LeadBot, "ontario": OntarioBot, "keeper": KeeperBot, "zone": ZoneBot, "wall": WallBot}
