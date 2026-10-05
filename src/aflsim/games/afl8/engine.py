"""The game engine: an 8-a-side match (4-a-side with Rules.four_a_side()) on an oval with a goal at each end,
stepped in decision intervals.

Team A (A1-A8) scores at x = length and defends x = 0; team B (B1-B8) the reverse. The
episode starts with a ball-up at the centre and ends when a goal is kicked (a behind is
followed by a kick-in from the goal square) or when the clock runs out.

Controllers hand in standing orders once per decision interval (and again straight after
key events); the engine integrates the physics in small steps, resolving kicks, handballs,
flights, marks, spoils, loose-ball contests, tackles, bounces, boundary restarts, scoring,
kick-ins and set plays. Nothing here chooses a tactic: every rule is a law of the game, a
capability or a stochastic mechanic (see config.py).

Standing orders per player (they persist until replaced):
  MOVE(x, y)                 run to the point, then stop (a set-play taker who MOVEs is playing on)
  HOLD                       stop
  ATTEMPT_POSSESSION         run to the ball (or where it will land) and contest it; chase the carrier if an opponent holds it
  ATTEMPT_MARK               run to where the kick will land and contest the mark
  SPOIL                      run to where the kick will land and punch it away (loose ball) instead of marking it
  TACKLE(opponent)           run at the opponent and tackle when within reach (only works on the ball carrier)
  KICK(x, y, power)          as soon as this player holds the ball, kick towards (x, y)
  HANDBALL(x, y | player, power)

Set plays: a mark or a free kick puts the taker `set_play_retreat` m behind the mark, places the nearest
opponent on the mark where they must stand still, and keeps other opponents `protected_area` m away (they can't
enter it, but are otherwise free to run: only the taker and the man on the mark stand still). The
taker is unpressured and cannot be tackled until they play on (MOVE, handball, or running off the spot) or
`set_play_seconds` elapse. A kick-in after a behind is a set play without a man on the mark.

Reflexes (rules, not orders): any player within reach of a loose ball or a landing kick contests it. A carrier
must bounce every run_limit_m metres (a fumble is a loose ball). A disposal out of bounds on the full is a
free kick to the nearest opponent at the spot; any other ball over the boundary is thrown in. Possession
changes, marks, spills, bounces, free kicks, throw-ins and kick-ins raise a decision trigger.
"""
from __future__ import annotations

import math

import numpy as np

from .actions import Action
from .config import Rules
from .ground import Oval, goal_line_crossing, score_of
from .physics import Flight, launch, move_player, pressure_at
from .players import Player, sample_attributes

EVENT_FIELDS = ("kicks", "handballs", "marks", "spoils", "possessions", "contested_possessions", "turnovers", "shots", "tackles", "tackles_attempted",
                "bounces", "fumbled_bounces", "free_kicks", "throw_ins", "kick_ins", "set_shots", "play_ons", "restarts")
TEAMS = ("A", "B")
TEAM_KEYS = ("kicks", "handballs", "marks", "possessions", "shots", "tackles", "goals", "behinds")


def around_circle(pos, target, centre, radius):
    """Where to run to get from pos to target without crossing the circle: the target itself if the straight line is
    clear, otherwise the tangent point of the circle on the side the target lies (so the runner skirts round it)."""
    pos = np.asarray(pos, float); target = np.asarray(target, float); c = np.asarray(centre, float)
    seg = target - pos; L2 = float(seg @ seg)
    u = 0.0 if L2 < 1e-9 else min(1.0, max(0.0, float((c - pos) @ seg) / L2))
    if np.linalg.norm(pos + u * seg - c) >= radius:
        return target                                                       # the straight line is clear
    d = pos - c; dist = float(np.linalg.norm(d))
    if dist <= radius + 1e-6:
        return c + d / max(dist, 1e-6) * (radius + 0.5)                     # (inside: step out first)
    alpha = math.acos(radius / dist); base = math.atan2(d[1], d[0])
    side = 1.0 if (d[0] * (target - c)[1] - d[1] * (target - c)[0]) >= 0 else -1.0   # go round on the target's side
    a = base + side * (alpha + 0.5)                                         # a little past the tangent: keeps the runner at speed
    return c + radius * np.array([math.cos(a), math.sin(a)]) * 1.04


def other(team):
    return "B" if team == "A" else "A"


class Game:
    PROFILES = None                         # attribute profiles by role / archetype (None: config.ROLE_PROFILES); a game can override

    def __init__(self, rules: Rules = Rules(), seed: int = 0, attrs: dict | None = None):
        self.r = rules
        self.oval = Oval(rules)
        self.rng = np.random.default_rng(seed)
        self.seed = seed
        self.players: dict[str, Player] = {}
        for team in TEAMS:
            for i in range(rules.n_per_team):
                pid = "%s%d" % (team, i + 1)
                role, _, archetype = rules.lineup[i].partition(":")              # "line" or "line:archetype"
                a = attrs[pid] if attrs and pid in attrs else sample_attributes(self.rng, archetype or role, profiles=self.PROFILES)
                bonus = rules.ability_bonus[TEAMS.index(team)]
                if bonus:
                    a = {k: float(round(min(1.0, v + bonus), 2)) for k, v in a.items()}
                self.players[pid] = Player(pid, team, a, role=role, archetype=archetype, energy_floor=rules.energy_speed_floor,
                                           speed_scale=rules.speed_scale, accel_scale=rules.accel_scale)
        self.manual = set()                                                     # live play: players a human controls (no auto-contest)
        self.reset_positions()

    # ------------------------------------------------------------------ setup
    def reset_positions(self):
        r = self.r
        self.t = 0.0
        self.score = {"A": 0, "B": 0}
        self.result = None
        self.events: list[dict] = []
        self.stats = {k: 0 for k in EVENT_FIELDS}
        self.team_stats = {t: {k: 0 for k in TEAM_KEYS} for t in TEAMS}
        self.ball_state = "loose"; self.flight: Flight | None = None; self.flight_resolved = False
        self.ball_pos = np.array([r.length / 2, 0.0]); self.ball_vel = np.zeros(2); self.holder: str | None = None
        self.last_kick_team = None; self.last_touch_team = None
        self.trigger = None
        self.set_play = None                   # {"taker", "mark", "spot", "man_on_mark", "until"} while a set play holds
        for p in self.players.values():
            p.vel = np.zeros(2); p.move_target = None; p.clear_ball_orders(); p.held_since = -1; p.protected_until = -1; p.mark_spot = None; p.carried = 0.0
            p.frozen = False
        self._centre_ball_up()

    def _centre_ball_up(self):
        """Loose ball at the centre. The first midfielder of each side stands beside it and the other midfielders are in the
        centre square; defenders start spread across their defensive half and forwards across their attacking half
        (a quarter of the ground from the goal they defend / attack). Positions after that are the controllers' business."""
        r, rng = self.r, self.rng
        c = np.array([r.length / 2, 0.0])
        self.ball_pos = c + rng.normal(size=2) * 0.5; self.ball_vel = np.zeros(2); self.ball_state = "loose"; self.holder = None
        for team, sign in (("A", -1.0), ("B", 1.0)):                                     # A defends x = 0: its half is x < length / 2
            groups = {"midfielder": [], "defender": [], "forward": []}
            for pid in self.team_ids(team):
                groups[self.players[pid].role].append(pid)
            for k, pid in enumerate(groups["midfielder"]):
                if k == 0:
                    self.players[pid].pos = c + np.array([sign * 2.5, rng.uniform(-1, 1)])
                else:
                    self.players[pid].pos = self.oval.clip(c + np.array([sign * rng.uniform(4.0, 0.4 * r.centre_square), rng.uniform(-0.4, 0.4) * r.centre_square]))
            for role, xc in (("defender", r.own_goal_x(team) + (r.length * 0.25) * (1 if r.own_goal_x(team) == 0 else -1)),
                             ("forward", r.goal_x(team) + (r.length * 0.25) * (1 if r.goal_x(team) == 0 else -1))):
                ids = groups[role]; n = len(ids)
                for k, pid in enumerate(ids):
                    y = (k - (n - 1) / 2) * (0.3 * r.width / max(n - 1, 1)) if n > 1 else 0.0
                    self.players[pid].pos = self.oval.clip([xc + rng.uniform(-0.06, 0.06) * r.length, y + rng.uniform(-4.0, 4.0)])
        self.trigger = "ball-up"

    def team_ids(self, team):
        return [pid for pid, p in self.players.items() if p.team == team]

    # ------------------------------------------------------------------ orders
    def apply_actions(self, team: str, actions: list[Action], keep=()):
        """Orders for a team; a player not mentioned loses his ball orders, unless he is in `keep` (live play: the
        human's player keeps his orders while the bot orders his teammates)."""
        mentioned = set(keep)
        for a in actions:
            p = self.players.get(a.player)
            if p is None or p.team != team:
                continue
            mentioned.add(a.player)
            p.clear_ball_orders()
            if a.kind == "MOVE":
                p.move_target = self.oval.clip(a.target); p.pace = a.pace
                if self.set_play and self.set_play["taker"] == p.pid:
                    self._play_on("moved")
            elif a.kind == "HOLD":
                p.move_target = None
            elif a.kind in ("ATTEMPT_POSSESSION", "ATTEMPT_MARK"):
                p.contest = True; p.contest_kind = "mark" if a.kind == "ATTEMPT_MARK" else "possession"
            elif a.kind == "SPOIL":
                p.spoil = True
            elif a.kind == "TACKLE":
                p.tackle_target = a.opponent
            elif a.kind in ("KICK", "HANDBALL"):
                p.pending_kick = {"kind": "kick" if a.kind == "KICK" else "handball", "target": a.target, "target_player": a.target_player, "power": a.power}
                if self.holder != p.pid:                                              # "get it and kick": keep going for the ball
                    p.contest = True; p.contest_kind = "possession"
        for pid in self.team_ids(team):
            if pid not in mentioned:
                self.players[pid].clear_ball_orders()

    # ------------------------------------------------------------------ stepping
    def step(self):
        """One physics step (live play advances the game a step at a time, between its own decisions)."""
        self._substep(self.r.physics_dt)

    def step_decision(self):
        """A full decision interval of physics, ignoring early decision triggers (scripted tests use this)."""
        n0 = len(self.events)
        for _ in range(int(round(self.r.decision_interval / self.r.physics_dt))):
            if self.result is not None:
                break
            self._substep(self.r.physics_dt)
        return self.events[n0:]

    def run_window(self, on_frame=None, every=None):
        """The physics after one decision: until the next scheduled decision, or earlier when an event (a kick, a
        mark, a possession change...) triggers one. The ONE stepping loop: matches, rollouts and data generation all
        use it. `on_frame(snapshot)` is called every replay sample (None = headless), or every `every` physics steps
        (every=1: each step, for smooth slow-motion video). Returns (events, trigger)."""
        r = self.r
        n0 = len(self.events)
        sub = int(round(r.decision_interval / r.physics_dt)); every = every or max(1, int(round(r.replay_sample_dt / r.physics_dt)))
        self.trigger = None; t_dec = self.t; trigger = "scheduled"
        for k in range(sub):
            if self.done:
                break
            self._substep(r.physics_dt)
            if on_frame is not None and ((k + 1) % every == 0 or self.done):
                on_frame(self.snapshot())
            if r.event_decisions and self.trigger and self.t - t_dec >= r.min_decision_gap - 1e-9 and not self.done:
                trigger = self.trigger
                break
        return self.events[n0:], trigger

    def clone(self, seed=None, extend_s=None):
        """An independent copy of the whole game (rollouts, look-ahead, what-if). The copy shares nothing.
        seed: give the copy its own dice (np.random.default_rng(seed)), so rollouts can share common random numbers.
        extend_s: make sure the copy's siren is at least this many seconds away, so a rollout never hits full time."""
        import copy
        import dataclasses
        g = copy.deepcopy(self)
        if extend_s is not None:
            g.r = dataclasses.replace(g.r, episode_seconds=max(g.r.episode_seconds, g.t + float(extend_s)))
        if seed is not None:
            g.rng = np.random.default_rng(seed)
        return g

    def end(self, result, note=""):
        self._end(result, note)

    def meta(self) -> dict:
        """Per-game facts for the log: each player's attributes and role."""
        out = {"attrs": {pid: p.attrs for pid, p in self.players.items()}, "roles": {pid: p.role for pid, p in self.players.items()}}
        if any(p.archetype for p in self.players.values()):
            out["archetypes"] = {pid: p.archetype for pid, p in self.players.items()}
        return out

    @property
    def done(self):
        return self.result is not None

    def _log(self, etype, **kw):
        e = {"t": round(self.t, 2), "type": etype}; e.update(kw); self.events.append(e)

    def pressure_on(self, pid):
        p = self.players[pid]
        opp = [q.pos for q in self.players.values() if q.team != p.team and not q.frozen]        # a man standing the mark exerts no pressure
        return pressure_at(p.pos, opp, self.r)

    def _substep(self, dt):
        r = self.r
        sp = self.set_play
        for p in self.players.values():
            if p.frozen or (sp is not None and sp["taker"] == p.pid):
                p.vel = np.zeros(2); self._energy(p, dt)                                      # standing the mark / taking the set play: rest
                continue
            target = p.move_target; cap = {"sprint": r.pace_sprint, "run": r.pace_run, "jog": r.pace_jog}.get(p.pace, r.pace_run)
            auto = r.auto_contest and p.pid not in self.manual                       # a human-controlled player has no reflexes
            if auto and self.ball_state == "loose" and self.holder is None and np.linalg.norm(p.pos - self.ball_pos) <= r.loose_ball_reflex_radius:
                target = self.ball_pos; cap = r.pace_sprint                                # reflex: a loose ball within reach is always attacked
            elif (auto and self.ball_state == "flight" and self.flight is not None and p.pid != self.flight.kicker
                  and np.linalg.norm(p.pos - self.flight.landing) <= r.flight_reflex_radius):
                target = self.flight.landing; cap = r.pace_sprint                          # reflex: a kick coming down near you is contested
            elif p.tackle_target and p.tackle_target in self.players:
                target = self.players[p.tackle_target].pos; cap = r.pace_sprint
            elif (p.contest or p.spoil) and self.holder is None:
                target = self.flight.landing if (self.ball_state == "flight" and self.flight is not None) else self.ball_pos; cap = r.pace_sprint
            elif p.contest and self.holder is not None and self.holder != p.pid:
                target = self.players[self.holder].pos; cap = r.pace_sprint
            if (sp is not None and r.protected_area_free_run and target is not None and p.pid != sp["man_on_mark"]
                    and p.team != self.players[sp["taker"]].team):
                tk = self.players[sp["taker"]].pos
                if np.linalg.norm(target - tk) < r.protected_area:                     # heading into the protected area: pull up at its edge
                    away = p.pos - tk; n = np.linalg.norm(away)
                    target = self.oval.clip(tk + (away / n if n > 1e-6 else np.array([1.0, 0.0])) * (r.protected_area + 0.3))
                else:                                                                  # a run that would cross it: go round
                    target = self.oval.clip(around_circle(p.pos, target, tk, r.protected_area + 0.6))
            p.pos, p.vel = move_player(p.pos, p.vel, target, p.top_speed * cap, p.accel, dt, r, self.oval)
            self._energy(p, dt)
            if sp is not None and p.team != self.players[sp["taker"]].team and p.pid != sp["man_on_mark"]:
                self._keep_out(p, sp)
        self.t += dt
        if sp is not None and self.t >= sp["until"]:
            self._play_on("time")
        if self.holder is not None:
            h = self.players[self.holder]
            h.carried += float(np.linalg.norm(h.vel)) * dt; h.run_total += float(np.linalg.norm(h.vel)) * dt
            self.ball_pos = h.pos.copy(); self.ball_vel = h.vel.copy()
            if r.run_limit_m > 0 and h.carried >= r.run_limit_m and h.pending_kick is None:
                self._bounce(h)
            if self.holder is not None and h.pending_kick is not None and self.t - h.held_since >= r.min_possession_seconds - 1e-9:
                self._dispose(h, h.pending_kick); h.pending_kick = None                  # gathering time: a disposal takes a beat to leave
        if self.ball_state == "flight":
            self._advance_flight(dt)
        if self.ball_state == "loose":
            self._advance_loose(dt)
        if self.holder is not None:
            self._tackles(dt)
        if self.result is None and self.t >= r.episode_seconds - 1e-9:
            self._end("full_time" if r.end_on == "time" else "timeout")

    def _energy(self, p, dt):
        """Sprinting drains energy, jogging or standing restores it (rules energy_*); frozen players and set-play takers rest."""
        r = self.r; f = p.effort()
        if f > r.energy_sprint_fraction:
            ramp = ((f - r.energy_sprint_fraction) / max(1.0 - r.energy_sprint_fraction, 1e-6)) ** r.energy_ramp_power   # 0 at the threshold, 1 at a full sprint
            p.energy = max(0.0, p.energy - ramp * dt / (r.energy_sprint_seconds * (0.5 + p.attrs.get("endurance", 0.7))))
        elif f < r.energy_recover_fraction:                                                   # the stiller, the faster: standing = full rate, a jog under half
            rate = 1.0 - 0.6 * f / max(r.energy_recover_fraction, 1e-6)
            p.energy = min(1.0, p.energy + rate * dt / r.energy_recover_seconds)

    def _keep_out(self, p, sp):
        """An opponent can't come inside the protected area around the set-play taker. They are held on its edge, but
        only the part of their run heading in is stopped: they keep running around it or away (rules
        protected_area_free_run; engine v1 zeroed their speed instead, which froze anyone who touched the edge)."""
        taker = self.players[sp["taker"]]
        d = p.pos - taker.pos; n = np.linalg.norm(d)
        if n < self.r.protected_area:
            direction = d / n if n > 1e-6 else np.array([1.0, 0.0])
            p.pos = self.oval.clip(taker.pos + direction * self.r.protected_area)
            if self.r.protected_area_free_run:
                inward = float(np.dot(p.vel, direction))
                if inward < 0.0:
                    p.vel = p.vel - inward * direction                                     # drop the inward part, keep the rest
            else:
                p.vel = np.zeros(2)

    # ------------------------------------------------------------------ possession changes
    def _give(self, pid, protected: bool, man_on_mark=True, retreat=True):
        p = self.players[pid]
        prev_team = self.last_touch_team
        self.holder = pid; self.ball_state = "held"; self.flight = None
        self.ball_pos = p.pos.copy(); self.ball_vel = np.zeros(2)
        p.held_since = self.t; p.carried = 0.0; p.run_total = 0.0
        if prev_team is not None and prev_team != p.team:
            self.stats["turnovers"] += 1; self._log("turnover", to=pid)
        self.last_touch_team = p.team
        self.trigger = self.trigger or "possession"
        for q in self.players.values():
            if (self.r.contest_end_coast and (q.contest or q.spoil) and q.pid != pid and q.move_target is None
                    and np.linalg.norm(q.vel) > 1.0):                                        # run on a couple of strides, don't slam the brakes
                v = np.linalg.norm(q.vel)
                q.move_target = self.oval.clip(q.pos + q.vel / v * min(0.8 * v, 5.0))
            q.contest = False; q.contest_kind = ""; q.spoil = False
        if protected and man_on_mark and not any(q.team != p.team and np.linalg.norm(q.pos - p.pos) <= self.r.man_on_mark_radius for q in self.players.values()):
            protected = False                                                            # nobody defending: no set play, just play on
            self._log("play_on", by=pid, how="no opponent within %.0f m" % self.r.man_on_mark_radius)
        if protected:
            self._start_set_play(p, man_on_mark, retreat)
        else:
            p.protected_until = -1

    def _start_set_play(self, taker: Player, man_on_mark: bool, retreat: bool = True):
        r = self.r
        mark = taker.pos.copy()
        back = np.array([-1.0, 0.0]) if r.goal_x(taker.team) > 0 else np.array([1.0, 0.0])      # away from the goal the taker attacks
        spot = self.oval.clip(mark + back * r.set_play_retreat) if retreat else mark.copy()
        taker.pos = spot.copy(); taker.vel = np.zeros(2); taker.move_target = None
        taker.protected_until = self.t + r.set_play_seconds; taker.mark_spot = mark
        self.ball_pos = spot.copy()
        mom = None
        if man_on_mark:
            opp = [q for q in self.players.values() if q.team != taker.team]
            m = min(opp, key=lambda q: np.linalg.norm(q.pos - mark))
            if np.linalg.norm(m.pos - mark) > r.man_on_mark_radius:
                m = None
        if man_on_mark and m is not None:
            m.pos = mark.copy(); m.vel = np.zeros(2); m.frozen = True; m.move_target = None; m.clear_ball_orders(); mom = m.pid
        self.set_play = {"taker": taker.pid, "mark": mark, "spot": spot, "man_on_mark": mom, "until": self.t + r.set_play_seconds}
        for q in self.players.values():
            if q.team != taker.team and q.pid != mom:
                self._keep_out(q, self.set_play)
        self._log("set_play", taker=taker.pid, man_on_mark=mom, mark=[round(float(mark[0]), 1), round(float(mark[1]), 1)])

    def _play_on(self, how):
        sp = self.set_play
        if sp is None:
            return
        taker = self.players[sp["taker"]]
        taker.protected_until = -1; taker.mark_spot = None
        if sp["man_on_mark"]:
            self.players[sp["man_on_mark"]].frozen = False
        self.set_play = None
        if how != "disposal":
            self.stats["play_ons"] += 1
            self._log("play_on", by=taker.pid, how=how)
            if how == "time":
                self.trigger = self.trigger or "play on called"

    def _drop(self, pos, vel):
        if self.set_play is not None:
            self._play_on("disposal")
        self.holder = None; self.ball_state = "loose"; self.flight = None
        self.ball_pos = self.oval.clip(pos) if not self.oval.inside(pos) else np.array(pos, float); self.ball_vel = np.array(vel, float)
        self.trigger = self.trigger or "loose ball"

    def _bounce(self, h: Player):
        r = self.r
        p_ok = min(max(r.bounce_base + 0.45 * h.attrs["ground_ball_skill"] - r.bounce_speed_penalty * h.speed_fraction(), 0.2), 0.98)
        h.carried = 0.0
        if self.rng.random() < p_ok:
            self.stats["bounces"] += 1; self._log("bounce", by=h.pid, ok=True)
        else:
            self.stats["fumbled_bounces"] += 1; self._log("bounce", by=h.pid, ok=False)
            ahead = h.vel / max(np.linalg.norm(h.vel), 1e-6) if np.linalg.norm(h.vel) > 0.1 else np.array([1.0, 0.0])
            h.held_since = -1; h.protected_until = -1
            self._drop(h.pos + ahead * 1.5 + self.rng.normal(size=2) * 0.8, h.vel * 0.5); self.trigger = "fumbled bounce"

    def _dispose(self, h: Player, order):
        kind, power = order["kind"], float(order["power"])
        if order.get("target_player"):
            tp = self.players[order["target_player"]]; target = tp.pos + tp.vel * 0.6
        else:
            target = np.array(order["target"], float)
        set_shot = self.set_play is not None and self.set_play["taker"] == h.pid
        if self.set_play is not None and self.set_play["taker"] == h.pid and kind == "handball":
            self._play_on("handball")                                                      # a handball from a set play is playing on
        pres = self.pressure_on(h.pid)
        gx = self.r.goal_x(h.team); dirn = 1.0 if gx > 0 else -1.0
        if kind == "kick" and abs(target[1]) < self.r.behind_half_width + 3.0 and -3.0 <= dirn * (target[0] - gx) <= self.r.shot_target_push and abs(target[0] - h.pos[0]) > 0.5:
            f = (gx - h.pos[0]) / (target[0] - h.pos[0])                                 # where the kicker-to-target line crosses the goal line
            cross = np.array([gx, h.pos[1] + f * (target[1] - h.pos[1])])
            u = cross - h.pos; u = u / max(np.linalg.norm(u), 1e-6)
            target = cross + u * self.r.shot_target_push                                 # a shot at the line is carried through that same point
        fl, sigma = launch(self.rng, self.r, h.pos.copy(), target, kind, power, h, pres, self.t, h.speed_fraction())
        is_shot = bool(kind == "kick" and (target[0] >= gx - 1.0 if gx > 0 else target[0] <= gx + 1.0) and abs(target[1]) < self.r.behind_half_width + 3.0)
        key = "kicks" if kind == "kick" else "handballs"
        self.stats[key] += 1; self.team_stats[h.team][key] += 1
        if is_shot:
            self.stats["shots"] += 1; self.team_stats[h.team]["shots"] += 1
            if set_shot and kind == "kick":
                self.stats["set_shots"] += 1
        self._log(kind, by=h.pid, target=[round(float(target[0]), 1), round(float(target[1]), 1)], power=round(power, 2), pressure=round(pres, 2),
                  requested_distance=round(fl.requested_distance, 1), error_sigma=round(sigma, 2), landing=[round(float(fl.landing[0]), 1), round(float(fl.landing[1]), 1)],
                  flight_time=round(fl.duration, 2), shot=is_shot, set_play=bool(set_shot))
        if self.set_play is not None and self.set_play["taker"] == h.pid:
            self._play_on("disposal")
        self.holder = None; h.held_since = -1; h.protected_until = -1; h.mark_spot = None
        self.ball_state = "flight"; self.flight = fl; self.flight_resolved = False
        if kind == "kick":
            self.trigger = "kick"                                                     # both teams get orders while the ball is in the air
        self.last_kick_team = h.team if kind == "kick" else None
        self.ball_pos = h.pos.copy()

    # ------------------------------------------------------------------ goal lines and boundary
    def _check_goal_lines(self, prev, now, kicked_by_team, on_the_full):
        r = self.r
        for team in TEAMS:
            y = goal_line_crossing(prev, now, r.goal_x(team))
            if y is None:
                continue
            kind = score_of(y, r)
            if kind == "out":
                return self._out(prev, now, on_the_full)
            if kind == "goal" and kicked_by_team != team:
                kind = "behind"                                                          # only a kick by the attacking side is a goal; anything else a rushed behind
            self._score(team, kind, y)
            return True
        if not self.oval.inside(now):
            return self._out(prev, now, on_the_full)
        return False

    def _out(self, prev, now, on_the_full):
        spot = self.oval.crossing(prev, now)
        if on_the_full is not None:
            team = self.players[on_the_full].team
            taker = min((p for p in self.players.values() if p.team != team), key=lambda p: np.linalg.norm(p.pos - spot))
            taker.pos = self.oval.clip(spot); taker.vel = np.zeros(2); self.flight = None
            self.stats["free_kicks"] += 1
            self._log("out_on_the_full", by=on_the_full, free_kick_to=taker.pid, spot=[round(float(spot[0]), 1), round(float(spot[1]), 1)])
            self._give(taker.pid, protected=True); self.trigger = "free kick (out on the full)"
        else:
            place = self.oval.clip(spot + self.oval.inward(spot) * self.r.throw_in_distance + self.rng.normal(size=2) * 1.0)
            self.stats["throw_ins"] += 1
            self._log("throw_in", spot=[round(float(spot[0]), 1), round(float(spot[1]), 1)], placed=[round(float(place[0]), 1), round(float(place[1]), 1)])
            self.last_kick_team = None; self.flight = None
            self._drop(place, np.zeros(2)); self.trigger = "throw-in"
        return True

    def _score(self, team, kind, y):
        r = self.r
        self.score[team] += r.goal_points if kind == "goal" else r.behind_points
        self.team_stats[team]["goals" if kind == "goal" else "behinds"] += 1
        self._log("score", team=team, kind=kind, y=round(y, 1), score=dict(self.score))
        if r.end_on == "score" or (kind == "goal" and r.end_on == "goal"):
            self._end(("goal_" if kind == "goal" else "behind_") + team)
        elif kind == "goal":
            self._restart_centre()
        else:
            self._kick_in(other(team))

    def _restart_centre(self):
        """After a goal: every order and contest is cleared and the game restarts with a centre ball-up."""
        self.set_play = None; self.flight = None; self.flight_resolved = False; self.holder = None
        self.last_kick_team = None; self.last_touch_team = None; self.ball_vel = np.zeros(2)
        for p in self.players.values():
            p.vel = np.zeros(2); p.move_target = None; p.clear_ball_orders(); p.carried = 0.0
            p.held_since = -1.0; p.protected_until = -1.0; p.mark_spot = None; p.frozen = False
        self._centre_ball_up()
        self.stats["restarts"] += 1; self._log("restart", how="centre ball-up after a goal")

    def _kick_in(self, team):
        r = self.r
        gx = r.own_goal_x(team)
        spot = np.array([gx + (r.goal_square_depth if gx == 0 else -r.goal_square_depth), 0.0])
        taker = min((p for p in self.players.values() if p.team == team), key=lambda p: np.linalg.norm(p.pos - spot))
        taker.pos = spot.copy(); taker.vel = np.zeros(2)
        for p in self.players.values():
            if p.team != team and np.linalg.norm(p.pos - spot) < r.kick_in_clearance:
                away = p.pos - spot; n = np.linalg.norm(away)
                d = away / n if n > 1e-6 else np.array([1.0 if gx == 0 else -1.0, 0.0])
                p.pos = self.oval.clip(spot + d * r.kick_in_clearance); p.vel = np.zeros(2)
        self.flight = None; self.stats["kick_ins"] += 1
        self._log("kick_in", by=taker.pid)
        self.last_touch_team = team
        self._give(taker.pid, protected=True, man_on_mark=False, retreat=False); self.trigger = "kick-in"

    # ------------------------------------------------------------------ flight
    def _advance_flight(self, dt):
        r, fl = self.r, self.flight
        prev = self.ball_pos.copy()
        self.ball_pos = fl.position(self.t); self.ball_vel = fl.ground_velocity()
        if self._check_goal_lines(prev, self.ball_pos, self.last_kick_team if fl.kind == "kick" else None, on_the_full=fl.kicker):
            return
        if not self.flight_resolved and fl.frac(self.t) > 0.5 and fl.contestable(self.t, r):
            cands = self._catch_candidates(fl.landing)
            if cands:
                self.flight_resolved = True; self._resolve_catch(cands)
                if self.ball_state != "flight":
                    return
        if fl.landed(self.t):
            if not self.flight_resolved:
                cands = self._catch_candidates(fl.landing)
                if cands:
                    self.flight_resolved = True; self._resolve_catch(cands)
                    if self.ball_state != "flight":
                        return
            self._drop(fl.landing, fl.ground_velocity() * r.roll_fraction); self.trigger = self.trigger or "ball landed"

    def _catch_candidates(self, landing):
        r = self.r
        return [p for p in self.players.values() if not p.frozen and (p.contest or p.spoil or (r.auto_contest and p.pid not in self.manual))
                and np.linalg.norm(p.pos - landing) <= r.mark_radius]

    def _resolve_catch(self, cands):
        r, fl = self.r, self.flight
        markable = fl.kind == "kick" and fl.requested_distance >= r.mark_min_kick_distance and fl.distance >= r.mark_min_kick_distance
        contested = len(cands) > 1 and len({p.team for p in cands}) > 1
        # defenders arriving by reflex (no explicit order) spoil when the contest is shared, and only try to mark when alone
        auto_spoil = {p.pid for p in cands if contested and fl.kind == "kick" and p.team != fl.kicker[0] and not p.contest and not p.spoil}
        for p in [p for p in cands if (p.spoil or p.pid in auto_spoil) and fl.kind == "kick" and p.team != fl.kicker[0]]:
            d = np.linalg.norm(p.pos - fl.landing)
            w = r.spoil_skill_factor * (r.mark_base + r.mark_skill_gain * p.attrs["marking_skill"]) * max(1.0 - r.mark_distance_gain * d / r.mark_radius, 0.0) / (1.0 + r.mark_pressure_gain * self.pressure_on(p.pid) ** 2 * (1.5 - p.attrs["marking_skill"]))
            if self.rng.random() < min(w, 1.0):
                self.stats["spoils"] += 1; self._log("spoil", by=p.pid, contested=contested, kick_distance=round(fl.distance, 1))
                away = fl.landing - p.pos; n = np.linalg.norm(away)
                away = away / n if n > 1e-6 else np.array([-1.0, 0.0])
                self._drop(fl.landing, away * self.rng.uniform(3.0, 6.0) + self.rng.normal(size=2) * 1.0); self.trigger = "spoil"
                return
        cands = [p for p in cands if not p.spoil and p.pid not in auto_spoil]
        if not cands:
            return
        if markable:                                                                   # marks: near-certain when unpressured, pressure squared bites close in
            weights = np.array([(r.mark_base + r.mark_skill_gain * p.attrs["marking_skill"]) * max(1.0 - r.mark_distance_gain * np.linalg.norm(p.pos - fl.landing) / r.mark_radius, 0.0)
                                / (1.0 + r.mark_pressure_gain * self.pressure_on(p.pid) ** 2 * (1.5 - p.attrs["marking_skill"])) for p in cands])   # skill resists pressure
        else:                                                                          # catches of short kicks / handballs: a ground-ball skill contest
            weights = np.array([p.attrs["ground_ball_skill"] * max(1.0 - 0.5 * np.linalg.norm(p.pos - fl.landing) / r.mark_radius, 0.0)
                                / (1.0 + self.pressure_on(p.pid)) for p in cands])
        p_any = 1.0 - np.prod(1.0 - np.clip(weights, 0, 1))
        if self.rng.random() < p_any and weights.sum() > 0:
            winner = cands[self.rng.choice(len(cands), p=weights / weights.sum())]
            if markable:
                self.stats["marks"] += 1; self.team_stats[winner.team]["marks"] += 1
                self._log("mark", by=winner.pid, contested=contested, kick_distance=round(fl.distance, 1), pressure=round(self.pressure_on(winner.pid), 2))
                self._give(winner.pid, protected=True)
            else:
                self._count_possession(winner, contested); self._log("possession", by=winner.pid, contested=contested, how="caught")
                self._give(winner.pid, protected=False)
        else:
            self._log("spill", candidates=[p.pid for p in cands], contested=contested); self.trigger = self.trigger or "spill"

    def _count_possession(self, p, contested):
        self.stats["possessions"] += 1; self.team_stats[p.team]["possessions"] += 1
        if contested:
            self.stats["contested_possessions"] += 1

    # ------------------------------------------------------------------ loose ball
    def _advance_loose(self, dt):
        r = self.r
        prev = self.ball_pos.copy()
        self.ball_pos = self.ball_pos + self.ball_vel * dt
        self.ball_vel = self.ball_vel * math.exp(-r.roll_decay * dt)
        if self._check_goal_lines(prev, self.ball_pos, self.last_kick_team, on_the_full=None):
            return
        cands = [p for p in self.players.values() if not p.frozen and (p.contest or p.spoil or r.auto_contest) and np.linalg.norm(p.pos - self.ball_pos) <= r.possession_radius]
        if not cands:
            return
        hz = np.array([r.gather_rate * (0.5 + 0.5 * p.attrs["ground_ball_skill"]) * max(1.0 - 0.5 * np.linalg.norm(p.pos - self.ball_pos) / r.possession_radius, 0.0)
                       / (1.0 + 0.6 * self.pressure_on(p.pid)) / (1.0 + r.gather_speed_penalty * p.speed_fraction()) for p in cands])
        if hz.sum() > 0 and self.rng.random() < 1.0 - math.exp(-hz.sum() * dt):
            winner = cands[self.rng.choice(len(cands), p=hz / hz.sum())]
            contested = (len(cands) > 1 and len({p.team for p in cands}) > 1) or self.pressure_on(winner.pid) > 0.5
            self._count_possession(winner, contested); self._log("possession", by=winner.pid, contested=bool(contested), how="ground")
            self._give(winner.pid, protected=False)

    # ------------------------------------------------------------------ tackles
    def _tackles(self, dt):
        r = self.r
        h = self.players[self.holder]
        if h.protected_until > self.t:
            return
        for p in self.players.values():
            if p.tackle_target != h.pid or p.team == h.team or p.frozen:
                continue
            d = np.linalg.norm(p.pos - h.pos)
            if d > r.tackle_radius:
                continue
            closing = max(float(np.dot(p.vel - h.vel, (h.pos - p.pos) / max(d, 1e-6))), 0.0)
            hazard = r.tackle_rate * p.attrs["tackling_skill"] / max(h.attrs["tackling_skill"], 0.2) * (1.0 - d / r.tackle_radius) * (1.0 + 0.1 * closing)
            self.stats["tackles_attempted"] += 1
            if self.rng.random() < 1.0 - math.exp(-hazard * dt):
                self.stats["tackles"] += 1; self.team_stats[p.team]["tackles"] += 1
                if self.t - h.held_since >= r.holding_the_ball_seconds or h.run_total >= r.prior_opportunity_m:      # prior opportunity
                    self._log("tackle", by=p.pid, on=h.pid, outcome="holding the ball: free kick"); self.stats["free_kicks"] += 1
                    self._give(p.pid, protected=True); self.trigger = "free kick"
                else:
                    self._log("tackle", by=p.pid, on=h.pid, outcome="ball spilled")
                    h.held_since = -1; h.protected_until = -1
                    self._drop(h.pos + self.rng.normal(size=2) * 1.0, h.vel * 0.3); self.trigger = "tackle"
                return

    def _end(self, result, note=""):
        if self.set_play is not None:
            self._play_on("disposal")
        self.result = result
        self._log("end", result=result, score=dict(self.score), note=note)

    # ------------------------------------------------------------------ observation
    def observation(self, recent_events=None) -> dict:
        r = self.r
        rd = lambda v: [round(float(v[0]), 1), round(float(v[1]), 1)]
        ball = {"state": self.ball_state, "position": rd(self.ball_pos), "velocity": rd(self.ball_vel), "owner": self.holder}
        if self.ball_state == "flight" and self.flight is not None:
            fl = self.flight
            ball["flight"] = {"kind": fl.kind, "from": fl.kicker, "lands_at": rd(fl.landing), "lands_in_s": round(fl.t0 + fl.duration - self.t, 2),
                              "distance": round(fl.distance, 1), "markable": bool(fl.kind == "kick" and fl.requested_distance >= r.mark_min_kick_distance)}
        if self.holder is not None:
            h = self.players[self.holder]
            ball["held_for_s"] = round(self.t - h.held_since, 1)
            if r.run_limit_m > 0:
                ball["run_since_bounce_m"] = round(h.carried, 1); ball["run_this_possession_m"] = round(h.run_total, 1)
        if self.set_play is not None:
            sp = self.set_play
            ball["set_play"] = {"taker": sp["taker"], "man_on_the_mark": sp["man_on_mark"], "mark": rd(sp["mark"]), "play_on_called_in_s": round(sp["until"] - self.t, 1)}
        teams = {t: [{"id": p.pid, "role": p.role, **({"archetype": p.archetype} if p.archetype else {}), "pos": rd(p.pos), "vel": rd(p.vel), "attrs": p.attrs, "energy": round(p.energy, 2), "pressure": round(self.pressure_on(p.pid), 2),
                      "moving_to": rd(p.move_target) if p.move_target is not None else None, **({"standing_the_mark": True} if p.frozen else {})}
                     for p in self.players.values() if p.team == t] for t in TEAMS}
        return {"time": round(self.t, 1), "time_left": round(r.episode_seconds - self.t, 1), "score": dict(self.score), "ball": ball,
                "team_A": teams["A"], "team_B": teams["B"],
                "goals": {"A_scores_at_x": r.goal_x("A"), "B_scores_at_x": r.goal_x("B"), "goal_posts_y": [-r.goal_half_width, r.goal_half_width],
                          "behind_posts_y": [-r.behind_half_width, r.behind_half_width]},
                "recent_events": recent_events or []}

    def snapshot(self) -> dict:
        return {"t": round(self.t, 2), "energy": {pid: round(p.energy, 2) for pid, p in self.players.items()}, "pos": {pid: [round(float(p.pos[0]), 2), round(float(p.pos[1]), 2)] for pid, p in self.players.items()},
                "ball": [round(float(self.ball_pos[0]), 2), round(float(self.ball_pos[1]), 2)], "state": self.ball_state, "holder": self.holder,
                "protected": bool(self.set_play is not None), "man_on_mark": self.set_play["man_on_mark"] if self.set_play else None,
                "landing": [round(float(self.flight.landing[0]), 2), round(float(self.flight.landing[1]), 2)] if self.flight is not None and self.ball_state == "flight" else None,
                "height": round(self.flight.height(self.t), 2) if self.flight is not None and self.ball_state == "flight" else 0.0, "score": dict(self.score)}
