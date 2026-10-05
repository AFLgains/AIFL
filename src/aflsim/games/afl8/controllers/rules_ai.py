"""A rules-based team: structured, sensible football with no model calls. A fixed opponent to test team packs
against for free, and a training partner for learned controllers.

Principles (all hand-written, so this is the one controller that does contain football knowledge):
- Structure: defenders man-mark the opposing forwards goal-side and push up behind the ball; forwards lead in
  three lanes when we have the ball and hold width otherwise; one midfielder attacks each contest, the other
  supports behind it or drops as a spare defender.
- With the ball: shoot inside ~40 m and in front; else kick to a teammate leading into space, aimed where they
  will be; else a short handball to an unpressured teammate ahead; else kick long to the forward line.
- Without the ball: the two nearest tackle the carrier; kicks coming down are marked by the nearest teammate
  or spoiled by the nearest defender when the opponent is favoured; loose balls are attacked by the nearest two.
"""
from __future__ import annotations

import numpy as np

from ..actions import Action
from ..config import Rules
from ..ground import Oval
from aflsim.bots.base import TeamController


class RulesController(TeamController):
    name = "rules"

    def __init__(self, team: str, rules: Rules = Rules(), seed: int = 0, aggression: float = 0.5):
        super().__init__(team)
        self.r = rules; self.oval = Oval(rules); self.rng = np.random.default_rng(seed)
        self.aggression = float(np.clip(aggression, 0.0, 1.0))
        self.opp = "B" if team == "A" else "A"
        self.goal_x = rules.goal_x(team); self.own_x = rules.own_goal_x(team)
        self.dirn = 1.0 if self.goal_x > self.own_x else -1.0
        self.shoot_range = 36.0 + 16.0 * self.aggression
        self.contest_n = 3; self.tackle_n = 2                       # players sent to a contest / at the carrier
        self.name = "rules"

    # ------------------------------------------------------------------ geometry helpers
    def ahead(self, x, m):
        return x + self.dirn * m

    def to_goal(self, pos):
        return float(np.hypot(self.goal_x - pos[0], pos[1]))

    def clip(self, x, y):
        p = self.oval.clip(np.array([x, y], float))
        return [float(p[0]), float(p[1])]

    def kick_range(self, p):
        return self.r.kick_min_distance_scale + p["attrs"]["kick_power"] * (self.r.kick_max_distance_scale - self.r.kick_min_distance_scale)

    @staticmethod
    def dist(a, b):
        return float(np.hypot(a[0] - b[0], a[1] - b[1]))

    # ------------------------------------------------------------------ the decision
    def choose_actions(self, state, problems):
        mine = state["team_" + self.team]; theirs = state["team_" + self.opp]
        ball = state["ball"]; bpos = ball["position"]; holder = ball["owner"]
        by_id = {p["id"]: p for p in mine + theirs}
        roles = {p["id"]: p.get("role", "midfielder") for p in mine + theirs}
        my_def = [p for p in mine if roles[p["id"]] == "defender"]; my_mid = [p for p in mine if roles[p["id"]] == "midfielder"]; my_fwd = [p for p in mine if roles[p["id"]] == "forward"]
        their_fwd = [p for p in theirs if roles[p["id"]] == "forward"]; their_def = [p for p in theirs if roles[p["id"]] == "defender"]
        if not my_def or not my_fwd or not my_mid:                                 # 4 a side or odd lineups: treat by index
            my_mid = mine[:2]; my_def = mine[2:3] or mine[:1]; my_fwd = mine[3:] or mine[-1:]
            their_fwd = theirs[3:] or theirs[-1:]; their_def = theirs[2:3] or theirs[:1]
        assign = self._man_assignments(my_def, their_fwd)
        self._my_def_ids = [q["id"] for q in my_def]
        we_have = holder is not None and holder[0] == self.team
        they_have = holder is not None and holder[0] == self.opp
        flight = ball.get("flight"); landing = flight["lands_at"] if flight else None
        sp = ball.get("set_play")
        acts = {}
        lanes = self._lanes(len(my_fwd))
        near_ball = sorted(mine, key=lambda p: self.dist(p["pos"], landing or bpos))

        # ---- the carrier
        if we_have:
            me = by_id[holder]
            acts[holder] = self._dispose(me, mine, theirs, sp is not None and sp.get("taker") == holder)
        # ---- everyone else
        for p in mine:
            pid = p["id"]
            if pid in acts:
                continue
            role = roles[pid]; pos = p["pos"]
            marked_near = flight is not None and assign.get(pid) in by_id and self.dist(by_id[assign[pid]]["pos"], landing) < 12.0
            if flight is not None and self.dist(pos, landing) < 26 and (pid in [q["id"] for q in near_ball[:self.contest_n]] or marked_near):
                # a kick coming down near me: mark it, or spoil it if an opponent is favoured
                their_near = min(self.dist(q["pos"], landing) for q in theirs)
                mine_near = self.dist(pos, landing)
                ours = flight.get("from", "")[0] == self.team
                if flight.get("markable") and not ours and their_near < mine_near - 1.0:
                    acts[pid] = Action(pid, "SPOIL")
                else:
                    acts[pid] = Action(pid, "ATTEMPT_MARK" if flight.get("markable") else "ATTEMPT_POSSESSION")
                continue
            if ball["state"] == "loose" and (pid in [q["id"] for q in near_ball[:self.contest_n]] or self.dist(pos, bpos) < 15.0):
                acts[pid] = Action(pid, "ATTEMPT_POSSESSION"); continue
            if they_have and pid in [q["id"] for q in near_ball[:self.tackle_n]] and not (sp and sp.get("man_on_the_mark") == pid):
                acts[pid] = Action(pid, "TACKLE", opponent=holder); continue
            # structure by role
            if role == "defender":
                acts[pid] = self._defender(p, assign.get(pid), bpos, we_have, they_have, holder, by_id)
            elif role == "forward":
                k = [q["id"] for q in my_fwd].index(pid) if pid in [q["id"] for q in my_fwd] else 0
                acts[pid] = self._forward(p, lanes[k % len(lanes)], bpos, we_have, they_have, holder, by_id, their_def)
            else:
                k = [q["id"] for q in my_mid].index(pid) if pid in [q["id"] for q in my_mid] else 0
                acts[pid] = self._midfielder(p, k, bpos, we_have, they_have, holder, by_id, mine, theirs, landing)
        intent = "rules: %s" % ("attack" if we_have else "defend" if they_have else "contest")
        return intent, self._cover_instead_of_tackling(state, [acts[p["id"]] for p in mine if p["id"] in acts])

    def _cover_instead_of_tackling(self, state, acts):
        """At the opponent's set play the taker is protected: he can't be tackled and nobody may come inside the
        protected area. A player sent at him would only stand at its edge until play on, so instead he covers a free
        opponent near the ball (goal-side of them) or, if there is none, guards the space in front of the mark where the
        kick is likely to go. Once play on is called there is no set play and tackling resumes as normal."""
        sp = state["ball"].get("set_play")
        if not sp or not sp.get("taker") or sp["taker"][0] == self.team or not getattr(self.r, "protected_area_free_run", False):
            return acts                                                        # (engine v1 rules: the old behaviour, unchanged)
        taker, mark = sp["taker"], sp["mark"]
        mine = {p["id"]: p for p in state["team_" + self.team]}
        theirs = [q for q in state["team_" + self.opp] if q["id"] != taker]
        covered, spare, out = set(), 0, []
        for a in acts:
            if a.kind == "TACKLE" and a.opponent == taker and a.player in mine:
                me = mine[a.player]["pos"]
                free = sorted((q for q in theirs if q["id"] not in covered and self.dist(q["pos"], mark) < 30.0), key=lambda q: self.dist(q["pos"], me))
                if free:
                    q = free[0]; covered.add(q["id"])
                    a = Action(a.player, "MOVE", target=self.clip(q["pos"][0] - self.dirn * 2.0, q["pos"][1]), pace="run")   # goal-side of them
                else:
                    a = Action(a.player, "MOVE", pace="run", target=self.clip(mark[0] - self.dirn * (self.r.protected_area + 10.0 + 6.0 * spare),
                                                                             mark[1] + (-8.0, 8.0, 0.0)[spare % 3]))
                    spare += 1
            out.append(a)
        return out

    # ------------------------------------------------------------------ with the ball
    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]; rng_k = self.kick_range(me)
        d_goal = self.to_goal(pos)
        if d_goal <= min(self.shoot_range + (6.0 if set_play else 0.0), rng_k * 0.95) and abs(pos[1]) < 22.0:
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=min(1.0, d_goal / rng_k + 0.15))
        # a lead: teammate ahead, 15-45 m away, open at where they will be when the ball lands
        best, best_score = None, -1e9
        for q in mine:
            if q["id"] == me["id"]:
                continue
            d = self.dist(pos, q["pos"])
            if d < 15.0 or d > min(rng_k * 0.9, 48.0):
                continue
            adv = self.dirn * (q["pos"][0] - pos[0])
            if adv < -5.0:
                continue
            tof = self.r.kick_flight_base + d / self.r.kick_ground_speed
            proj = [q["pos"][0] + q["vel"][0] * tof, q["pos"][1] + q["vel"][1] * tof]
            space = min(self.dist(o["pos"], proj) for o in theirs)
            score = adv + 2.0 * min(space, 10.0) - 6.0 * q["pressure"] + 4.0 * q["attrs"]["marking_skill"]
            if space >= 5.0 and score > best_score:
                best, best_score, best_proj, best_d = q, score, proj, self.dist(pos, proj)
        if best is not None:
            t = self.clip(*best_proj)
            return Action(me["id"], "KICK", target=t, power=min(1.0, best_d / rng_k + 0.12))
        # a handball to an unpressured teammate ahead or level
        hb = [q for q in mine if q["id"] != me["id"] and 3.0 < self.dist(pos, q["pos"]) <= 14.0 and self.dirn * (q["pos"][0] - pos[0]) > -4.0 and q["pressure"] < 0.7]
        if hb:
            q = max(hb, key=lambda q: self.dirn * q["pos"][0] - 4.0 * q["pressure"])
            return Action(me["id"], "HANDBALL", target_player=q["id"], power=min(1.0, self.dist(pos, q["pos"]) / 16.0 + 0.25))
        # kick long to the forward line, to the side with fewer opponents
        side = -1.0 if sum(1 for o in theirs if o["pos"][1] > 0 and self.dirn * (o["pos"][0] - pos[0]) > 0) > sum(1 for o in theirs if o["pos"][1] <= 0 and self.dirn * (o["pos"][0] - pos[0]) > 0) else 1.0
        target = self.clip(self.ahead(pos[0], min(rng_k * 0.85, 45.0)), side * 14.0)
        if self.dirn * (target[0] - pos[0]) < 10.0 or d_goal <= min(58.0, rng_k):   # near goal, or a long bomb is on: the goal square
            target = [self.goal_x, 0.0]
        return Action(me["id"], "KICK", target=target, power=min(1.0, self.dist(pos, target) / rng_k + 0.15))

    # ------------------------------------------------------------------ roles without the ball
    def _man_assignments(self, my_def, their_fwd):
        d = sorted(my_def, key=lambda p: p["pos"][1]); f = sorted(their_fwd, key=lambda p: p["pos"][1])
        return {d[i]["id"]: f[i % len(f)]["id"] for i in range(len(d))} if f else {}

    def _lanes(self, n):
        span = 0.32 * self.r.width
        return [(-span + 2 * span * i / max(n - 1, 1)) if n > 1 else 0.0 for i in range(n)]

    def _defender(self, p, mark_id, bpos, we_have, they_have, holder, by_id):
        pos = p["pos"]
        if they_have or not we_have:
            if mark_id and mark_id in by_id:
                f = by_id[mark_id]["pos"]
                tx = f[0] - self.dirn * 4.0; ty = f[1] * 0.9                  # goal-side of the forward, between them and our goal
                tx = self.own_x + self.dirn * max(self.dirn * (tx - self.own_x), 8.0)
                return Action(p["id"], "MOVE", target=self.clip(tx, ty))
            return Action(p["id"], "MOVE", target=self.clip(self.own_x + self.dirn * 30.0, pos[1] * 0.5))
        # we have it: push up behind the ball, keeping 25-40 m behind it and goal-side of the forward
        depth = self.dirn * (bpos[0] - self.own_x)
        tx = self.own_x + self.dirn * float(np.clip(depth - 30.0, 10.0, self.r.length * 0.55))
        ty = (by_id[mark_id]["pos"][1] * 0.6 if mark_id and mark_id in by_id else pos[1] * 0.6)
        return Action(p["id"], "MOVE", target=self.clip(tx, ty))

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        pos = p["pos"]
        if we_have:
            carrier = by_id[holder]["pos"]
            lead = self.ahead(carrier[0], 30.0 + 8.0 * self.rng.random())
            lead = self.own_x + self.dirn * min(self.dirn * (lead - self.own_x), self.r.length - 12.0)
            return Action(p["id"], "MOVE", target=self.clip(lead, lane_y))
        if they_have:
            d_goal_theirs = self.dirn * (bpos[0] - self.own_x)                 # how deep the ball is in our end
            if d_goal_theirs > self.r.length * 0.6:                             # ball in their defence: press their defenders
                nearest = min(their_def, key=lambda o: self.dist(o["pos"], pos)) if their_def else None
                if nearest and self.dist(nearest["pos"], pos) < 25.0:
                    return Action(p["id"], "TACKLE", opponent=holder) if nearest["id"] == holder else Action(p["id"], "MOVE", target=self.clip(nearest["pos"][0] - self.dirn * 2.0, nearest["pos"][1]))
            hold_x = self.own_x + self.dirn * min(self.dirn * (bpos[0] - self.own_x) + 20.0, self.r.length * 0.72)
            return Action(p["id"], "MOVE", target=self.clip(hold_x, lane_y))
        # ball loose or in flight: hold width around 25 m ahead of the ball
        return Action(p["id"], "MOVE", target=self.clip(self.ahead(bpos[0], 25.0), lane_y))

    def _midfielder(self, p, k, bpos, we_have, they_have, holder, by_id, mine, theirs, landing):
        pos = p["pos"]
        if we_have:
            carrier = by_id[holder]["pos"]
            if k == 0:
                return Action(p["id"], "MOVE", target=self.clip(carrier[0] - self.dirn * 8.0, carrier[1] + (6.0 if carrier[1] < 0 else -6.0)))   # the receiver behind
            return Action(p["id"], "MOVE", target=self.clip(self.ahead(carrier[0], 22.0), carrier[1] * 0.3))                              # the runner ahead
        if they_have:
            if k == 0:
                return Action(p["id"], "TACKLE", opponent=holder)
            return Action(p["id"], "MOVE", target=self.clip(bpos[0] - self.dirn * 15.0, bpos[1] * 0.5))                                   # the spare behind the ball
        target = landing or bpos
        return Action(p["id"], "ATTEMPT_POSSESSION") if self.dist(pos, target) < 30.0 else Action(p["id"], "MOVE", target=self.clip(target[0], target[1]))


class DefensiveRulesController(RulesController):
    """The contest-and-defend variant: the same structure, but everyone gets behind the ball when the opponent has it
    (forwards flood back to within 10 m of the ball, the second midfielder sits in the hole in front of the most
    dangerous forward), four players go to every contest and three to the carrier, defenders mark tight and spoil,
    and with the ball it never shoots from beyond 30 m and clears to the boundary side out of its defensive third."""
    name = "defence"

    def __init__(self, team: str, rules: Rules = Rules(), seed: int = 0, aggression: float = 0.2):
        super().__init__(team, rules, seed, aggression)
        self.shoot_range = 30.0
        self.contest_n = 4; self.tackle_n = 3
        self.name = "defence"

    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]; rng_k = self.kick_range(me)
        deep = self.dirn * (pos[0] - self.own_x) < 45.0                           # in our defensive third
        if deep and me["pressure"] > 0.6:                                          # under pressure near our goal: clear long to the boundary side
            side = 1.0 if pos[1] >= 0 else -1.0
            target = self.clip(self.ahead(pos[0], min(rng_k * 0.9, 45.0)), side * 0.4 * self.r.width)
            return Action(me["id"], "KICK", target=target, power=min(1.0, self.dist(pos, target) / rng_k + 0.15))
        return super()._dispose(me, mine, theirs, set_play)

    def _defender(self, p, mark_id, bpos, we_have, they_have, holder, by_id):
        if (they_have or not we_have) and mark_id and mark_id in by_id:
            f = by_id[mark_id]["pos"]
            tx = f[0] - self.dirn * 2.5; ty = f[1]                                  # tight, 2.5 m goal-side of the forward
            tx = self.own_x + self.dirn * max(self.dirn * (tx - self.own_x), 6.0)
            return Action(p["id"], "MOVE", target=self.clip(tx, ty))
        if we_have:                                                                # push up, but no closer than 35 m behind the ball
            depth = self.dirn * (bpos[0] - self.own_x)
            tx = self.own_x + self.dirn * float(np.clip(depth - 35.0, 10.0, self.r.length * 0.45))
            ty = (by_id[mark_id]["pos"][1] * 0.6 if mark_id and mark_id in by_id else p["pos"][1] * 0.6)
            return Action(p["id"], "MOVE", target=self.clip(tx, ty))
        return super()._defender(p, mark_id, bpos, we_have, they_have, holder, by_id)

    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        if they_have:                                                               # flood: stay within 10 m ahead of the ball, spread across the lanes
            d_ball = self.dirn * (bpos[0] - self.own_x)
            if d_ball > self.r.length * 0.7:                                       # ball deep in their defence: one presses, the rest hold the centre
                return super()._forward(p, lane_y, bpos, we_have, they_have, holder, by_id, their_def)
            hold_x = self.own_x + self.dirn * min(d_ball + 10.0, self.r.length * 0.55)
            return Action(p["id"], "MOVE", target=self.clip(hold_x, lane_y))
        if we_have:                                                                # shorter leads: 22 m, easier to hit and mark
            carrier = by_id[holder]["pos"]
            lead = self.ahead(carrier[0], 22.0 + 6.0 * self.rng.random())
            lead = self.own_x + self.dirn * min(self.dirn * (lead - self.own_x), self.r.length - 12.0)
            return Action(p["id"], "MOVE", target=self.clip(lead, lane_y))
        return Action(p["id"], "MOVE", target=self.clip(self.ahead(bpos[0], 12.0), lane_y))      # loose or in flight: close to the ball

    def _midfielder(self, p, k, bpos, we_have, they_have, holder, by_id, mine, theirs, landing):
        if they_have and k == 1:                                                   # the hole: 14 m goal-side of the ball, in the corridor
            return Action(p["id"], "MOVE", target=self.clip(bpos[0] - self.dirn * 14.0, bpos[1] * 0.4))
        if we_have and k == 1:
            carrier = by_id[holder]["pos"]
            return Action(p["id"], "MOVE", target=self.clip(self.ahead(carrier[0], 15.0), carrier[1] * 0.3))
        return super()._midfielder(p, k, bpos, we_have, they_have, holder, by_id, mine, theirs, landing)
