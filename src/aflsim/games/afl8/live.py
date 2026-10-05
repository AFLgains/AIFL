"""Live play: a game in real time with a human controlling one player (the rest of his team run by a helper bot).

The engine is the real one, stepped one physics step (0.05 s) at a time in a background thread. The bots decide on
their usual schedule (every decision interval, or earlier at an event); the human's player gets fresh orders every
step from the latest input, and keeps them when his helper bot orders the others (apply_actions(..., keep=)). He has
no reflexes (game.manual): he contests a ball only when the human presses for it, inside the timing window.

Controls (the browser sends a direction, sprint, and presses):
  with the ball      move; "kick:<power>" (power 0..1.25 from the meter: distance; over 1.0 sprays); "handball"
  without the ball   move; "action": a kick coming down -> leap for the mark (only inside the window, else too
                     early: locked out briefly); a loose ball -> go and gather it; their carrier near -> tackle;
                     "spoil" (a kick coming down: punch it away, same window)
  "switch" / "switch:<dx>,<dy>"   take another teammate (the best placed / the one that way)
Control also moves on its own: to our carrier when we win it, to the receiver of our kick or handball, to whoever is
best placed for their kick or the loose ball, to the man nearest their carrier when they win it.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from .actions import Action
from .render.broadcast import ground_data, pack_frame, sprite_sheet
from .render.replay import TICKER_EVENTS, chain_timeline, player_tags, ticker_text

WINDOW = 0.6            # a leap counts within this many seconds of the ball coming down
ARCADE = {              # the feel of the playable game (both teams; research games and ladders keep the real physics)
    "accel_scale": 3.0,               # 2.5-5 m/s2 -> 7.5-15: off the mark and turning in a stride, not three seconds
    "speed_scale": 1.2,               # top speed 6.5-9 m/s -> 7.8-10.8
    "pace_run": 0.95,                 # normal running is nearly flat out (Shift still adds the last bit, and burns energy)
    "energy_speed_floor": 0.75,       # a tired player slows to three-quarter pace, not half
    "min_possession_seconds": 0.15,   # a kick leaves in 0.15 s, not 0.4
}
GOAL_HOLD, BEHIND_HOLD = 2.5, 1.0


def unit(v):
    v = np.asarray(v, float); n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.zeros(2)


class LiveMatch:
    def __init__(self, g, opponent: str, helper: str, seconds: float = 240.0, human: str = "A", seed: int | None = None, game_name: str = "afl8",
                 names: dict | None = None):
        from aflsim.bots.registry import load_bot
        self.g = g; self.seed = int(seed if seed is not None else time.time()) % 1_000_000
        self.r = g.make_rules(seconds, **ARCADE); self.game = g.new_game(self.r, self.seed, mirror=True)
        self.human = human; self.opp = "B" if human == "A" else "A"
        self.bots = {human: load_bot(helper, human, self.r, self.seed, game_name), self.opp: load_bot(opponent, self.opp, self.r, self.seed + 1000, game_name)}
        self.names = names or {human: "YOU", self.opp: opponent.split("/")[-1].replace("zoo:", "")}
        self.pids = sorted(self.game.players, key=lambda p: (p[0], int(p[1:])))
        self.mine = [p for p in self.pids if p[0] == human]
        self.problems = {"A": [], "B": []}; self.recent = []; self.t_dec = -1e9; self.trigger = "start"
        self.input = {"dir": [0.0, 0.0], "sprint": False}; self.presses = []
        self.order = None; self.disposal = None; self.lockout = 0.0; self.notes = []
        self.frames = []; self.events_out = []; self.n_events = 0
        self.lock = threading.Lock(); self.status = "playing"; self.hold_until = 0.0; self.last_poll = time.time()
        self.control = min(self.mine, key=lambda p: np.linalg.norm(self.game.players[p].pos - self.game.ball_pos))
        self.game.manual = {self.control}
        self.thread = threading.Thread(target=self._run, daemon=True); self.thread.start()

    # ------------------------------------------------------------ what the browser needs once
    def static(self) -> dict:
        meta = self.game.meta(); meta["roles"] = {p: self.game.players[p].role for p in self.pids}
        return {"names": self.names, "pids": self.pids, "roles": meta["roles"], "tags": player_tags(meta), "ground": ground_data(self.r),
                "sprites": sprite_sheet(), "seconds": self.r.episode_seconds, "human": self.human, "window": WINDOW}

    # ------------------------------------------------------------ the browser's tick: input in, frames and events out
    def tick(self, since: int, ev_since: int, inp: dict | None, presses: list | None) -> dict:
        with self.lock:
            self.last_poll = time.time()
            if inp:
                self.input = {"dir": [float(inp.get("dir", [0, 0])[0]), float(inp.get("dir", [0, 0])[1])], "sprint": bool(inp.get("sprint"))}
            if presses:
                self.presses += [str(p) for p in presses][:20]
            frames = self.frames[since + 1:] if since >= -1 else self.frames[-1:]
            events = self.events_out[ev_since:]
            nxt = self._candidate()
            return {"frames": frames, "seq": len(self.frames) - 1, "events": events, "ev": len(self.events_out), "status": self.status, "error": getattr(self, "error", None),
                    "control": {"pid": self.control, "next": nxt, "order": self.order[0] if self.order else None},
                    "notes": [n for n in self.notes if time.time() - n[2] < 1.2]}

    def stop(self):
        self.status = "stopped"

    # ------------------------------------------------------------ the loop
    def _run(self):
        try:
            self._loop()
        except Exception as e:                                               # noqa: BLE001  (report it, don't die silently)
            import traceback
            self.error = traceback.format_exc(); self.status = "error"
            self.events_out.append({"k": "error", "t": round(self.game.t, 2), "text": "%s: %s" % (type(e).__name__, e)})

    def _loop(self):
        g, r = self.game, self.r
        next_t = time.time()
        while self.status == "playing":
            if time.time() - self.last_poll > 20.0:                          # nobody watching: stop
                self.status = "abandoned"; break
            now = time.time()
            if now < self.hold_until:
                time.sleep(0.02); next_t = time.time(); continue
            with self.lock:
                if self.trigger or g.t - self.t_dec >= r.decision_interval - 1e-9:
                    self._decide()
                self._human()
                n0 = len(g.events)
                g.step()
                new = g.events[n0:]; self.recent += new
                if r.event_decisions and g.trigger and g.t - self.t_dec >= r.min_decision_gap - 1e-9:
                    self.trigger = g.trigger
                self._events(new)
                self._auto_switch(new)
                f = pack_frame(g.snapshot(), self.pids)
                if g.ball_state == "flight" and g.flight is not None:
                    f["li"] = round(g.flight.t0 + g.flight.duration - g.t, 2); f["kt"] = g.flight.kicker[0]
                self.frames.append(f)
                if g.done:
                    self.status = "finished"; self.events_out.append({"k": "end", "t": round(g.t, 2), "result": g.result}); break
            next_t += r.physics_dt
            time.sleep(max(0.0, next_t - time.time()))

    def _decide(self, only=None):
        g = self.game
        state = g.observation(self.recent); state["decision_reason"] = self.trigger or "scheduled"
        for team, bot in self.bots.items():
            if only and team != only:
                continue
            hook = getattr(bot, "observe_game", None) or getattr(getattr(bot, "inner", None), "observe_game", None)
            if hook is not None:
                hook(g)
            try:
                _intent, actions = bot.choose_actions(state, self.problems[team])
            except Exception:                                                # noqa: BLE001  (SafeBot already catches; belt and braces)
                actions = []
            self.problems[team] = getattr(bot, "last_problems", [])
            if team == self.human:
                g.apply_actions(team, [a for a in actions if a.player != self.control], keep={self.control})
            else:
                g.apply_actions(team, actions)
        if not only:
            self.recent = []; self.t_dec = g.t; self.trigger = None; g.trigger = None

    # ------------------------------------------------------------ the human's player
    def _note(self, text):
        self.notes.append([round(self.game.t, 2), text, time.time(), self.control])
        self.notes = self.notes[-6:]

    def _human(self):
        g, r = self.game, self.r
        p = g.players[self.control]; pos = p.pos
        d = unit(self.input["dir"]) if np.linalg.norm(self.input["dir"]) > 0.25 else np.zeros(2)
        presses, self.presses = self.presses, []
        act = None
        for pr in presses:
            if pr.startswith("switch"):
                self._switch(pr); p = g.players[self.control]; pos = p.pos
        if g.holder == self.control:
            self.order = None
            for pr in presses:
                if pr.startswith("kick:"):
                    act = self._kick(p, d, float(pr.split(":")[1]))
                elif pr == "handball":
                    act = self._handball(p, d)
                if act is not None:
                    self.disposal = (act, g.t + 1.5)                         # a kick winds up: keep the order until the ball goes
            if act is None and self.disposal and g.t < self.disposal[1]:
                act = self.disposal[0]
        else:
            self.disposal = None
        if g.holder != self.control:
            for pr in presses:
                if pr in ("action", "spoil"):
                    self._contest(p, pr)
            if self.order:
                kind, until = self.order
                if until():
                    act = Action(self.control, kind) if kind != "TACKLE" else Action(self.control, "TACKLE", opponent=g.holder)
                else:
                    self.order = None
        if act is None:
            if np.linalg.norm(d) > 0:
                act = Action(self.control, "MOVE", target=[float(pos[0] + d[0] * 6), float(pos[1] + d[1] * 6)], pace="sprint" if self.input["sprint"] else "run")
            else:
                act = Action(self.control, "HOLD")
        g.apply_actions(self.human, [act], keep=[q for q in self.mine if q != self.control])

    def _kick(self, p, d, power):
        g, r = self.game, self.r
        rng = r.kick_min_distance_scale + p.attrs["kick_power"] * (r.kick_max_distance_scale - r.kick_min_distance_scale)
        goal = np.array([r.length if self.human == "A" else 0.0, 0.0]); pos = p.pos
        to_goal = goal - pos; dist_goal = float(np.linalg.norm(to_goal))
        if not np.any(d):
            d = unit(to_goal)
        reach = max(10.0, min(power, 1.0) * rng)
        target = pos + d * reach
        ang = lambda u, v: float(np.degrees(np.arccos(np.clip(np.dot(unit(u), unit(v)), -1, 1))))
        if ang(d, to_goal) < 16 and dist_goal <= rng * 1.05 and power >= 0.55:
            target = goal.copy()                                             # a shot: aimed between the posts
        else:                                                                 # light aim assist: a teammate leading into that kick
            best = None
            for q in self.mine:
                if q == self.control:
                    continue
                tq = g.players[q]; lead = tq.pos + tq.vel * (0.8 + reach / 25.0)
                a = ang(d, lead - pos); dd = float(np.linalg.norm(lead - pos))
                if a < 20 and abs(dd - reach) < 14 and (best is None or a < best[0]):
                    best = (a, lead)
            if best is not None:
                target = best[1]
        if power > 1.0:                                                       # held too long: the kick sprays
            spray = np.radians((power - 1.0) * 160 * (1 if np.random.random() < 0.5 else -1))
            c, s = np.cos(spray), np.sin(spray); v = target - pos
            target = pos + np.array([c * v[0] - s * v[1], s * v[0] + c * v[1]]); self._note("SPRAYED IT")
        target = g.oval.clip(np.asarray(target, float))
        return Action(self.control, "KICK", target=[float(target[0]), float(target[1])], power=1.0)

    def _handball(self, p, d):
        g, r = self.game, self.r
        best = None
        for q in self.mine:
            if q == self.control:
                continue
            v = g.players[q].pos - p.pos; dd = float(np.linalg.norm(v))
            if dd < 2 or dd > 18:
                continue
            a = float(np.degrees(np.arccos(np.clip(np.dot(unit(v), d), -1, 1)))) if np.any(d) else 0.0
            score = a + dd * 1.5
            if (not np.any(d) or a < 60) and (best is None or score < best[0]):
                best = (score, q)
        if best is None:
            self._note("NO ONE THERE"); return None
        return Action(self.control, "HANDBALL", target_player=best[1])

    def _contest(self, p, press):
        g = self.game
        if g.t < self.lockout:
            return
        if g.ball_state == "flight" and g.flight is not None:
            li = g.flight.t0 + g.flight.duration - g.t; far = float(np.linalg.norm(p.pos - g.flight.landing))
            if li > WINDOW:
                self.lockout = g.t + 0.5; self._note("TOO EARLY"); return
            if far > 7.0:
                self._note("TOO FAR"); return
            kind = "SPOIL" if press == "spoil" else "ATTEMPT_MARK"
            self.order = (kind, lambda: g.ball_state == "flight"); self._note("SPOIL!" if kind == "SPOIL" else "LEAP!")
        elif press == "action" and g.holder is None:
            self.order = ("ATTEMPT_POSSESSION", lambda: g.holder is None)
        elif press == "action" and g.holder and g.holder[0] == self.opp:
            if float(np.linalg.norm(p.pos - g.players[g.holder].pos)) <= 7.0:
                target = g.holder; t_end = g.t + 1.2
                self.order = ("TACKLE", lambda: g.holder == target and g.t < t_end); self._note("TACKLE!")
            else:
                self._note("TOO FAR")

    # ------------------------------------------------------------ who the human controls
    def _set_control(self, pid):
        if pid == self.control or pid not in self.mine:
            return
        old = self.control; self.control = pid; self.order = None
        self.game.manual = {pid}
        self._decide(only=self.human)                                       # the helper bot takes the old player back at once
        _ = old

    def _best_for_ball(self, exclude=None):
        g = self.game
        spot = g.flight.landing if (g.ball_state == "flight" and g.flight is not None) else (g.players[g.holder].pos if g.holder else g.ball_pos)
        cands = [q for q in self.mine if q != exclude]
        return min(cands, key=lambda q: float(np.linalg.norm(g.players[q].pos - spot)))

    def _candidate(self):
        try:
            return self._best_for_ball(exclude=self.control)
        except ValueError:
            return None

    def _switch(self, press):
        g = self.game
        if ":" in press:
            try:
                dx, dy = (float(v) for v in press.split(":")[1].split(","))
            except ValueError:
                dx = dy = 0.0
            d = unit([dx, dy]); me = g.players[self.control].pos
            best = None
            for q in self.mine:
                if q == self.control:
                    continue
                v = g.players[q].pos - me; dd = float(np.linalg.norm(v))
                a = float(np.degrees(np.arccos(np.clip(np.dot(unit(v), d), -1, 1))))
                if a < 50 and (best is None or a * 0.5 + dd < best[0]):
                    best = (a * 0.5 + dd, q)
            if best:
                self._set_control(best[1])
        else:
            self._set_control(self._best_for_ball(exclude=self.control))

    def _auto_switch(self, new):
        """Control follows the play, but calmly: always to our own ball carrier; otherwise only to a teammate who is
        clearly better placed (8 m nearer the ball), and not within a second of the last switch."""
        g = self.game
        for e in new:
            k = e["type"]
            if k in ("possession", "mark", "free_kick", "kick_in") and g.holder and g.holder[0] == self.human:
                self._set_control(g.holder); self.last_auto = g.t
                return
        if not any(e["type"] in ("kick", "handball", "possession", "mark", "free_kick", "kick_in", "spill", "spoil", "turnover") for e in new):
            return
        if g.t - getattr(self, "last_auto", -9.0) < 1.0 or g.holder == self.control:
            return
        kicker = next((e.get("by") for e in new if e["type"] in ("kick", "handball")), None)
        best = self._best_for_ball(exclude=kicker if kicker and kicker[0] == self.human else None)
        spot = g.flight.landing if (g.ball_state == "flight" and g.flight is not None) else (g.players[g.holder].pos if g.holder else g.ball_pos)
        gap = float(np.linalg.norm(g.players[self.control].pos - spot) - np.linalg.norm(g.players[best].pos - spot))
        if best != self.control and (gap > 8.0 or self.control == kicker):
            self._set_control(best); self.last_auto = g.t

    # ------------------------------------------------------------ events for the browser (ticker, scores, sounds, chain)
    def _events(self, new):
        g = self.game
        for e in new:
            out = {"k": e["type"], "t": round(e["t"], 2), "by": e.get("by") or e.get("taker") or e.get("to")}
            if e["type"] in TICKER_EVENTS:
                out["text"] = ticker_text(e, self.names)
            if e["type"] == "score":
                out.update(team=e["team"], kind=e.get("kind"))
                self.hold_until = time.time() + (GOAL_HOLD if e.get("kind") == "goal" else BEHIND_HOLD)
            self.events_out.append(out)
        if new:
            ch = chain_timeline({"events": g.events})[-1]
            self.events_out.append({"k": "chain", "t": round(ch[0], 2), "team": ch[1], "text": ch[2]})
