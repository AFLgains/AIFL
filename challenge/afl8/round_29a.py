"""contrarian 29a: contrarian_28a with the flood gated by a trigger (flood_mode), so it fires against race-model kick choosers and not against the rest of the pool.

28a: contrarian_25a + the flood. When they have the ball (outside their defensive third), two forwards drop
into the 22-42 m band in front of their carrier, each covering the landing spot their kick chooser would rate most valuable and still free
(a shadow of the champion's chooser, energy-aware), or a default lane; they jog at the spot. The third forward stays 20 m ahead as the outlet.

Original 25a: a fresh-legs zone and counter, built from scratch (not from the climb lineage).

Idea: the champion's race model rates every runner at full-energy top speed, and its two midfielders do all the
chasing (they sit at 0.2-0.3 energy from the 40 s mark). So: (1) keep the whole team fresh: nobody runs to a shape
spot, everybody jogs there, and only one designated presser (the freshest of the two nearest) chases the carrier;
(2) defend with a compact ball-relative zone (defenders a line 22 m goal-side, one mid in the hole, forwards 18 m
ahead of the ball, everybody within ~35 m so nobody has to sprint far) and contest every drop with whoever really
gets there first, using an ENERGY-AWARE race model (top speed x (0.5 + 0.5 energy)) that the champion lacks;
(3) with the ball, counter with handballs to fresh free teammates ahead, run when nobody can reach us, kick only to
spots our receiver wins on the energy-aware race, shoot inside ~38 m or from set plays. The taker holds a set play
while leads develop (the whole team rests meanwhile).
"""
from __future__ import annotations

import math

from aflsim.games.afl8.actions import Action
from aflsim.games.afl8.controllers.rules_ai import RulesController


class Bot(RulesController):
    def __init__(self, team, rules, seed):
        super().__init__(team, rules, seed, aggression=0.5)
        self.name = "contrarian_29a"
        self.flood_mode = "hold"; self._they_held = False; self._flood_on = False
        self.shadow = True; self.flood_depth = 30.0; self.flood_lanes = (-17.0, 17.0); self.flood_ks = (0, 1)

    # ------------------------------------------------------------------ energy-aware physics
    @staticmethod
    def top_speed(p):
        return (6.5 + 2.5 * p["attrs"]["speed"]) * (0.5 + 0.5 * p.get("energy", 1.0))

    @staticmethod
    def accel(p):
        return (2.5 + 2.5 * p["attrs"]["acceleration"]) * (0.5 + 0.5 * p.get("energy", 1.0))

    def travel_time(self, p, point, slack=0.0):
        d = self.dist(p["pos"], point) - slack
        if d <= 0:
            return 0.0
        v = self.top_speed(p); a = self.accel(p)
        dx = (point[0] - p["pos"][0], point[1] - p["pos"][1]); n = max(math.hypot(*dx), 1e-6)
        v0 = max(0.0, (p["vel"][0] * dx[0] + p["vel"][1] * dx[1]) / n)
        t_acc = max((v - v0) / a, 0.0)
        d_acc = v0 * t_acc + 0.5 * a * t_acc * t_acc
        if d <= d_acc:
            return (-v0 + math.sqrt(v0 * v0 + 2 * a * d)) / a
        return t_acc + (d - d_acc) / v

    def kick_sigma(self, p, d, pressure, speed_frac):
        return (0.3 + 0.085 * d) * (1 + 0.5 * pressure) * (1 + 0.4 * speed_frac) / (0.5 + 0.5 * p["attrs"]["kick_accuracy"])

    def goal_prob(self, p, pos, pressure, speed_frac):
        dx = self.goal_x - pos[0]; dy = -pos[1]; d = math.hypot(dx, dy)
        if d < 1.0:
            return 0.95
        sig = self.kick_sigma(p, d + 6.0, pressure, speed_frac) * (d / (d + 6.0)) / max(abs(dx) / d, 0.25)
        reach = self.kick_range(p) * max(1 - 0.12 * pressure, 0.3)
        if d + 3.0 > reach:
            return 0.0
        return 0.97 * math.erf(3.2 / (sig * math.sqrt(2.0)))

    def value_at(self, pos, kicker_like, pressure=0.2):
        pg = self.goal_prob(kicker_like, pos, pressure, 0.0)
        d = self.to_goal(pos)
        return max(6.0 * pg + 0.3, 4.2 * math.exp(-max(d - 30.0, 0.0) / 45.0))

    def value_theirs(self, pos):
        d = math.hypot(self.own_x - pos[0], pos[1])
        return 4.6 * math.exp(-max(d - 30.0, 0.0) / 45.0)

    def shape_x(self, bpos, offset, lo=8.0):
        x = bpos[0] + self.dirn * offset
        return self.own_x + self.dirn * float(min(max(self.dirn * (x - self.own_x), lo), self.r.length - 8.0))

    # ------------------------------------------------------------------ the decision
    def choose_actions(self, state, problems):
        mine = state["team_" + self.team]; theirs = state["team_" + self.opp]
        ball = state["ball"]; bpos = ball["position"]; holder = ball["owner"]
        self._ball = ball; self._time_left = state.get("time_left", 120.0); self._theirs = theirs; self._mine = mine; self._shadow_cache = None
        sp0 = ball.get("set_play")
        if sp0 and sp0.get("taker", " ")[0] == self.opp and ball.get("held_for_s", 0.0) >= 2.0:
            self._they_held = True                                                  # their kick chooser waits for leads: a race-model bot
        t_now = state.get("time", 0.0)
        their_mids = sorted((o.get("energy", 1.0) for o in theirs), key=float)[:2]
        m = self.flood_mode
        if m == "always":
            self._flood_on = True
        elif m == "never":
            self._flood_on = False
        elif m == "hold":
            self._flood_on = self._they_held
        elif m == "tired":
            self._flood_on = t_now > 40.0 and sum(their_mids) / 2.0 < 0.4
        elif m == "time":
            self._flood_on = t_now > 40.0
        elif m == "lead":
            sc = state.get("score", {}); self._flood_on = sc.get(self.team, 0) >= sc.get(self.opp, 0)
        elif m == "hold_tired":
            self._flood_on = self._they_held and t_now > 40.0 and sum(their_mids) / 2.0 < 0.45
        by_id = {p["id"]: p for p in mine + theirs}
        roles = {p["id"]: p.get("role", "midfielder") for p in mine}
        my_def = [p for p in mine if roles[p["id"]] == "defender"] or mine[2:5]
        my_mid = [p for p in mine if roles[p["id"]] == "midfielder"] or mine[:2]
        my_fwd = [p for p in mine if roles[p["id"]] == "forward"] or mine[5:]
        we_have = holder is not None and holder[0] == self.team
        they_have = holder is not None and holder[0] == self.opp
        flight = ball.get("flight"); landing = flight["lands_at"] if flight else None
        sp = ball.get("set_play")
        ref = landing or bpos
        live_theirs = [o for o in theirs if not o.get("standing_the_mark")]
        acts = {}

        if we_have:
            me = by_id[holder]
            acts[holder] = self._dispose(me, mine, theirs, sp is not None and sp.get("taker") == holder)

        # ---- a kick in the air: whoever truly gets to the drop goes (energy-aware), spoil when they are favoured
        if flight is not None:
            ours = flight.get("from", " ")[0] == self.team
            t_land = flight["lands_in_s"]
            my_t = sorted(((self.travel_time(p, landing, 2.0), p) for p in mine if p["id"] not in acts), key=lambda x: x[0])
            their_t = min((self.travel_time(o, landing, 2.5) for o in live_theirs), default=99.0)
            if ours:
                for k, (t, p) in enumerate(my_t[:2]):
                    if t <= t_land + (0.7 if k == 0 else 0.2):
                        acts[p["id"]] = Action(p["id"], "ATTEMPT_MARK" if flight.get("markable") else "ATTEMPT_POSSESSION")
            else:
                sent = 0
                for t, p in my_t:
                    if sent >= 3 or t > t_land + 0.9:
                        break
                    if flight.get("markable") and their_t <= max(t, t_land * 0.9) + 0.8:
                        acts[p["id"]] = Action(p["id"], "SPOIL")
                    else:
                        acts[p["id"]] = Action(p["id"], "ATTEMPT_MARK" if flight.get("markable") else "ATTEMPT_POSSESSION")
                    sent += 1

        # ---- loose ball: the two who get there first, and anyone within 8 m
        if ball["state"] == "loose":
            near = sorted(mine, key=lambda p: self.travel_time(p, bpos))
            for k, p in enumerate(near):
                if p["id"] in acts:
                    continue
                if k < 2 or self.dist(p["pos"], bpos) < 8.0:
                    acts[p["id"]] = Action(p["id"], "ATTEMPT_POSSESSION")

        # ---- they have it: one presser (the freshest of the two who can get there soonest), plus a second when he is in a pack
        if they_have:
            carrier = by_id[holder]
            protected = sp is not None and sp.get("taker") == holder
            cands = []
            for p in mine:
                if p["id"] in acts or (sp and sp.get("man_on_the_mark") == p["id"]):
                    continue
                t = self.travel_time(p, carrier["pos"], 1.5)
                cands.append((t, p))
            cands.sort(key=lambda x: x[0])
            pool = cands[:2]
            if pool:
                pool.sort(key=lambda x: x[0] - 1.5 * x[1].get("energy", 1.0))
                t, p = pool[0]
                if t < 5.0 and not (protected and t > 2.0):
                    acts[p["id"]] = Action(p["id"], "TACKLE", opponent=holder)
                if carrier["pressure"] > 0.6 and len(pool) > 1 and pool[1][0] < 2.0 and not protected:
                    q = pool[1][1]; acts[q["id"]] = Action(q["id"], "TACKLE", opponent=holder)

        # ---- the zone
        their_x = self.dirn * (ref[0] - self.own_x)
        for p in mine:
            pid = p["id"]
            if pid in acts:
                continue
            if p.get("standing_the_mark"):
                acts[pid] = Action(pid, "HOLD"); continue
            role = roles[pid]
            if role == "defender":
                k = my_def.index(p) if p in my_def else 0
                lane = (-1, 0, 1)[k % 3] * 0.2 * self.r.width
                if we_have:
                    tgt = self.clip(self.shape_x(ref, -22.0, 10.0), lane * 0.7 + ref[1] * 0.25)
                else:
                    tgt = self.clip(self.shape_x(ref, -20.0, 7.0), lane + ref[1] * 0.35)
                acts[pid] = Action(pid, "MOVE", target=tgt)
            elif role == "forward":
                k = my_fwd.index(p) if p in my_fwd else 0
                lanes = (-16.0, 16.0, 0.0)
                if we_have:
                    carrier = by_id[holder]
                    to_goal = self.dirn * (self.goal_x - carrier["pos"][0])
                    if to_goal < 48.0:
                        spots = [(17.0, -12.0), (17.0, 12.0), (28.0, 0.0)]
                        sx, sy = spots[k % 3]
                        x = self.goal_x - self.dirn * sx
                        if self.dirn * (x - carrier["pos"][0]) < 10.0:
                            x = carrier["pos"][0] + self.dirn * 10.0
                        acts[pid] = Action(pid, "MOVE", target=self.clip(x, sy)); continue
                    offs = [(34.0, -14.0), (34.0, 14.0), (20.0, 0.0)]
                    ox, oy = offs[k % 3]
                    x = self.shape_x(carrier["pos"], ox); y = carrier["pos"][1] * 0.3 + oy
                    near = [o for o in theirs if abs(o["pos"][0] - x) < 10.0 and abs(o["pos"][1] - y) < 8.0]
                    if near:
                        o = min(near, key=lambda o: abs(o["pos"][1] - y))
                        y = o["pos"][1] + math.copysign(9.0, (y - o["pos"][1]) or (oy or 1.0))
                    acts[pid] = Action(pid, "MOVE", target=self.clip(x, y))
                elif they_have and their_x > self.r.length * 0.62 and self.dist(p["pos"], bpos) < 25.0:
                    acts[pid] = Action(pid, "TACKLE", opponent=holder)
                elif they_have and k in self.flood_ks and self._flood_on:
                    spot = self._shadow_spot(p) if self.shadow else None                # the flood: sit where their chooser would kick
                    if spot is None:
                        spot = self.clip(self.own_x + self.dirn * max(their_x - self.flood_depth, 12.0), bpos[1] * 0.4 + self.flood_lanes[k % 2])
                    a = Action(pid, "MOVE", target=spot); a.flood = True; acts[pid] = a
                else:
                    acts[pid] = Action(pid, "MOVE", target=self.clip(self.shape_x(ref, 18.0 if they_have else 16.0), lanes[k % 3] + ref[1] * 0.3))
            else:
                k = my_mid.index(p) if p in my_mid else 0
                if we_have:
                    carrier = by_id[holder]
                    side = 1.0 if carrier["pos"][1] < 0 else -1.0
                    if k == 0:
                        tgt = self.clip(carrier["pos"][0] - self.dirn * 8.0, carrier["pos"][1] + side * 8.0)
                    else:
                        tgt = self.clip(self.ahead(carrier["pos"][0], 16.0), carrier["pos"][1] * 0.4 - side * 9.0)
                    acts[pid] = Action(pid, "MOVE", target=tgt)
                elif they_have:
                    acts[pid] = Action(pid, "MOVE", target=self.clip(self.shape_x(ref, -12.0 if k == 0 else -5.0, 6.0), ref[1] * 0.5 + (0.0 if k == 0 else 8.0)))
                else:
                    acts[pid] = Action(pid, "ATTEMPT_POSSESSION") if self.dist(p["pos"], ref) < 22.0 else Action(pid, "MOVE", target=self.clip(ref[0] - self.dirn * 4.0, ref[1]))

        # ---- pace: the rest budget. Shape moves jog unless far from the spot and fresh; the last 15 s sprint
        for pid, a in acts.items():
            if a.kind != "MOVE" or pid == holder:
                continue
            p = by_id[pid]; e = p.get("energy", 1.0); d = self.dist(p["pos"], a.target)
            if self._time_left < 15.0:
                a.pace = "sprint" if e > 0.1 else "run"
            elif d < 3.0:
                a.pace = "jog"
            elif getattr(a, "flood", False):
                a.pace = "run" if (d > 6.0 and e > 0.4) else "jog"                      # get to the band, then breathe there
            elif we_have and roles[pid] != "defender" and e > 0.35 and d > 6.0:
                a.pace = "run"                                                      # the counter: options run
            elif d > 22.0 and e > 0.6 and not we_have:
                a.pace = "run"
            else:
                a.pace = "jog"
        intent = "contrarian: %s" % ("attack" if we_have else "defend" if they_have else "contest")
        return intent, [acts[p["id"]] for p in mine if p["id"] in acts]

    # ------------------------------------------------------------------ the shadow: where would their chooser kick? (after counter_25b)
    def _shadow_spots(self):
        b = self._ball; holder = b.get("owner")
        if holder is None or holder[0] != self.opp:
            return []
        theirs = self._theirs; mine = self._mine
        me = next((o for o in theirs if o["id"] == holder), None)
        if me is None:
            return []
        pos = me["pos"]; reach = self.kick_range(me)
        odirn = -self.dirn; ogoal = self.own_x
        pres = me.get("pressure", 0.0); shorten = max(1 - 0.12 * pres, 0.3); eff_reach = reach * shorten
        cands = []
        for q in theirs:
            if q["id"] == holder:
                continue
            d0 = self.dist(pos, q["pos"]); tof0 = 0.8 + d0 / 22.0
            cands.append(self.clip(q["pos"][0] + q["vel"][0] * tof0 * 0.8, q["pos"][1] + q["vel"][1] * tof0 * 0.8))
        for ax in (22.0, 32.0, 42.0, 50.0):
            for ay in (-28.0, -14.0, 0.0, 14.0, 28.0):
                cands.append(self.clip(pos[0] + odirn * ax, pos[1] * 0.4 + ay))
        out = []
        for aim in cands:
            d = self.dist(pos, aim)
            if d * shorten < 16.0 or d > eff_reach - 1.5:
                continue
            land = [pos[0] + (aim[0] - pos[0]) * shorten, pos[1] + (aim[1] - pos[1]) * shorten]
            T = 0.8 + d * shorten / 22.0
            rt = min((self.travel_time(q, land, 2.0) for q in theirs if q["id"] != holder), default=99.0)
            if rt > T + 0.7:
                continue
            ot = min((self.travel_time(o, land, 4.5) for o in mine), default=99.0)
            margin = ot - max(0.88 * T, rt)
            dg = math.hypot(ogoal - land[0], land[1])
            v_them = 4.2 * math.exp(-max(dg - 30.0, 0.0) / 45.0) + (2.5 if dg < 45.0 else 0.0)
            out.append((v_them, margin, land))
        return out

    def _shadow_spot(self, p):
        if self._shadow_cache is None:
            self._shadow_cache = self._shadow_spots(); self._shadow_taken = []
        best, best_s = None, -1e9
        for v, margin, land in self._shadow_cache:
            if margin < -0.3:
                continue
            if any(self.dist(land, t) < 12.0 for t in self._shadow_taken):
                continue
            s = v - 0.06 * self.dist(p["pos"], land)
            if s > best_s:
                best, best_s = land, s
        if best is None:
            return None
        self._shadow_taken.append(best)
        return self.clip(*best)

    # ------------------------------------------------------------------ with the ball
    def _dispose(self, me, mine, theirs, set_play):
        pos = me["pos"]; reach = self.kick_range(me)
        pres = 0.0 if set_play else me["pressure"]
        sf = 0.0 if set_play else min(1.0, math.hypot(*me["vel"]) / self.top_speed(me))
        shorten = max(1 - 0.12 * pres, 0.3); eff_reach = reach * shorten
        live = [o for o in theirs if not o.get("standing_the_mark")]
        held = self._ball.get("held_for_s", 0.0)
        d_goal = self.to_goal(pos)
        pg = self.goal_prob(me, pos, pres, sf)
        if pg >= 0.6 or (set_play and pg >= 0.42) or (pg >= 0.4 and pres > 0.8):
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=1.0)
        shot_v = 6.0 * pg - 0.3 if pg > 0 else -9.0

        # the handball: a teammate 4-18 m away whom nobody reaches in time, fresher and further forward preferred
        hb_best, hb_v = None, -1e9
        for q in mine:
            if q["id"] == me["id"]:
                continue
            d = self.dist(pos, q["pos"])
            if d < 4.0 or d > 12.0 + 8.0 * me["attrs"]["handball_power"]:
                continue
            land = [q["pos"][0] + q["vel"][0] * 0.6, q["pos"][1] + q["vel"][1] * 0.6]
            T = 0.15 + d / 11.0
            ot = min((self.travel_time(o, land, 3.0) for o in live), default=99.0)
            if ot < T + (0.15 if pres >= 0.9 else 0.4):
                continue
            p_catch = 0.55 + 0.4 * q["attrs"]["ground_ball_skill"]
            v = (p_catch + (1 - p_catch) * 0.6) * self.value_at(land, q, 0.2 if ot > T + 1.5 else 0.7) - 0.25
            v += 0.6 * q.get("energy", 1.0) + 0.02 * self.dirn * (land[0] - pos[0])
            if v > hb_v:
                hb_best, hb_v = q, v
        if pres >= 0.9 and hb_best is not None and not set_play:
            return Action(me["id"], "HANDBALL", target_player=hb_best["id"], power=min(1.0, self.dist(pos, hb_best["pos"]) / 16.0 + 0.35))

        # the run: nobody can reach me for ~1.3 s (energy-aware) and I am fresh enough
        near_t = min((self.travel_time(o, pos, 2.0) for o in live), default=99.0)
        run_m = self._ball.get("run_this_possession_m", 0.0)
        if near_t > 1.3 and run_m < 28.0 and d_goal > 26.0 and me.get("energy", 1.0) > 0.3 and not (set_play and near_t < 2.5):
            return Action(me["id"], "MOVE", target=self.clip(self.ahead(pos[0], 14.0), pos[1] * 0.75))

        # the kick: to a spot our receiver wins on the energy-aware race
        best, best_v, best_keep = None, -1e9, 0.0
        cands = []
        for q in mine:
            if q["id"] == me["id"]:
                continue
            d0 = self.dist(pos, q["pos"]); tof0 = 0.8 + d0 / 22.0
            cands.append(self.clip(q["pos"][0] + q["vel"][0] * tof0 * 0.8, q["pos"][1] + q["vel"][1] * tof0 * 0.8))
            cands.append(list(q["pos"]))
        for ax in (20.0, 30.0, 40.0, 50.0):
            for ay in (-26.0, -13.0, 0.0, 13.0, 26.0):
                cands.append(self.clip(self.ahead(pos[0], ax), pos[1] * 0.4 + ay))
        for aim in cands:
            d = self.dist(pos, aim)
            if d * shorten < 16.0 or d > eff_reach - 1.5:
                continue
            aim_land = [pos[0] + (aim[0] - pos[0]) * shorten, pos[1] + (aim[1] - pos[1]) * shorten]
            T = 0.8 + d * shorten / 22.0
            sig = self.kick_sigma(me, d, pres, sf)
            rt, rq = min(((self.travel_time(q, aim_land, max(2.5 - 0.5 * sig, 0.5)), q) for q in mine if q["id"] != me["id"]), key=lambda x: x[0])
            ot = min((self.travel_time(o, aim_land, 3.0 + 0.6 * sig) for o in live), default=99.0)
            if rt > T + 0.7:
                continue
            margin = ot - max(0.88 * T, rt)
            p_keep = 0.25 + 0.7 * min(max((margin + 0.3) / 1.3, 0.0), 1.0)
            if rt > T + 0.2:
                p_keep *= 0.7
            v = p_keep * self.value_at(aim_land, rq, 0.2 if margin > 1.0 else 0.6) - (1 - p_keep) * 0.5 * self.value_theirs(aim_land)
            if pres > 0.8:
                v -= 0.6 + (pres - 0.8)
            if v > best_v:
                best, best_v, best_keep = aim, v, p_keep

        if hb_best is not None and hb_v >= best_v and hb_v >= shot_v and hb_v > 0.0:
            return Action(me["id"], "HANDBALL", target_player=hb_best["id"], power=min(1.0, self.dist(pos, hb_best["pos"]) / 16.0 + 0.35))
        if set_play and self._ball.get("set_play", {}).get("play_on_called_in_s", 0.0) > 1.5 and d_goal > 42.0 and (best is None or best_keep < 0.8):
            return Action(me["id"], "HOLD")                                       # rest: the whole team jogs while the leads develop
        if best is not None and best_v >= shot_v:
            return Action(me["id"], "KICK", target=best, power=1.0)
        if pg >= 0.3:
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=1.0)
        if best is not None:
            return Action(me["id"], "KICK", target=best, power=1.0)
        if pres < 0.25 and held < 0.8 and not set_play:
            return Action(me["id"], "MOVE", target=self.clip(self.ahead(pos[0], 6.0), pos[1]))
        side = 1.0 if pos[1] >= 0 else -1.0
        deep = self.dirn * (pos[0] - self.own_x) < 45.0
        t = self.clip(self.ahead(pos[0], min(eff_reach * 0.9, 48.0)), (side * 0.38 * self.r.width) if deep else side * 12.0)
        if d_goal <= eff_reach + 4.0 and abs(pos[1]) < 30:
            t = [self.goal_x, 0.0]
        return Action(me["id"], "KICK", target=t, power=1.0)
