"""Replay a saved episode as a retro broadcast-style animation (matplotlib). Never used during simulation.

    python -m <package>.replay path/to/game_log.json.gz [--speed 2] [--gif out.mp4] [--style retro|flat|classic]
    (in the league repo, normally via `python afl.py render <match_id>`)

Layout: a scoreboard across the top (team names, AFL-style goals.behinds (points), clock), the oval in the
middle, a coach panel on each side (team A, which defends the left goal, on the left; team B on the right) with a
pixelated coach portrait (face.png / face.jpg in the team pack folder, else a drawn face) and a speech bubble that
shows the coach's latest plan, an event ticker and the possession chain along the bottom. "retro" (default) draws
the ground in the tilted pseudo-3D perspective of 16-bit sports games, with sprite players that scale with depth
and a red oval ball that spins in flight; "flat" is the same sprites seen from straight above; "classic" is the old
flat-disc view. Goals freeze the picture for a celebration before play resumes; full time holds the final score.
"""
from __future__ import annotations

import argparse
import json
import textwrap

import numpy as np

from ..config import Rules
from aflsim.engine.logs import load_log as load_episode
from ..ground import Oval
from . import sprites

COL = {"A": "#e53935", "B": "#1e88e5"}
TICKER_EVENTS = ("mark", "spoil", "tackle", "free_kick", "out_on_the_full", "throw_in", "kick_in", "score", "restart", "bounce", "play_on", "set_play")
MONO = "DejaVu Sans Mono"


# ----------------------------------------------------------------------------- pseudo-3D camera
class Camera:
    """Tilted-pitch perspective of 16-bit sports games: the near touchline (y = -width/2) is at the bottom of the
    screen at full width, the far touchline is compressed. proj(x, y) -> screen (X, Y); scale(y) -> sprite size factor."""

    def __init__(self, r: Rules, k: float = 0.6, height: float | None = None, on: bool = True):
        self.r = r; self.k = k if on else 0.0; self.on = on
        self.cx = r.length / 2; self.w = r.width + 6.0
        self.H = height if height is not None else (r.width * 0.98 if on else r.width + 6.0)
        self.ylim = None                                            # set by animate() when the camera is framed to the panel

    def depth(self, y):
        return np.clip((np.asarray(y, float) + self.w / 2) / self.w, 0.0, 1.0)

    def scale(self, y):
        return 1.0 / (1.0 + self.k * self.depth(y))

    def proj(self, x, y):
        x = np.asarray(x, float); y = np.asarray(y, float)
        s = self.scale(y)
        if not self.on:
            return x, y
        d = self.depth(y)
        Y = -self.H / 2 + self.H * (1.0 - 1.0 / (1.0 + self.k * d)) / (1.0 - 1.0 / (1.0 + self.k))
        X = self.cx + (x - self.cx) * s
        return X, Y

    def limits(self):
        if not self.on:
            return (-5, self.r.length + 5), (-self.w / 2, self.w / 2)
        return (-6, self.r.length + 6), (self.ylim if self.ylim else (-self.H / 2 - 1, self.H / 2 + 7))


def draw_ground(ax, r: Rules, cam: Camera, retro: bool = True):
    from matplotlib.patches import Polygon
    artists = {}
    ov = Oval(r)
    x, y = ov.outline(600)
    ax.set_facecolor("#0f3d16" if retro else "#1b5e20")
    lw = 3 if retro else 2
    X, Y = cam.proj(x, y)
    ax.add_patch(Polygon(np.column_stack([X, Y]), closed=True, fc="#2e7d32" if not retro else "#34823c", ec="none", zorder=0))
    if retro:                                                                   # mown stripes, clipped to the oval
        outline = Polygon(np.column_stack([X, Y]), closed=True, fc="none", ec="none")
        ax.add_patch(outline)
        for i, x0 in enumerate(np.arange(-5, r.length + 5, 10.0)):
            xs = np.array([x0, x0 + 10, x0 + 10, x0]); ys = np.array([-cam.w / 2, -cam.w / 2, cam.w / 2, cam.w / 2])
            px, py = cam.proj(xs, ys)
            stripe = Polygon(np.column_stack([px, py]), closed=True, fc="#2c7434" if i % 2 else "#3a8a42", ec="none", zorder=0.5)
            ax.add_patch(stripe); stripe.set_clip_path(outline)
    ax.plot(np.append(X, X[0]), np.append(Y, Y[0]), color="white", lw=lw, zorder=1)
    ln = ov.lines()
    th = np.linspace(0, 2 * np.pi, 120)
    cx, cy, rad = ln["centre_circle"]; px, py = cam.proj(cx + rad * np.cos(th), cy + rad * np.sin(th)); ax.plot(px, py, color="white", lw=lw - 1, zorder=1)
    sx, sy, sw, sh = ln["centre_square"]; px, py = cam.proj([sx, sx + sw, sx + sw, sx, sx], [sy, sy, sy + sh, sy + sh, sy]); ax.plot(px, py, color="white", lw=lw - 1, zorder=1)
    for gx in (0.0, r.length):
        a0 = np.linspace(-np.pi / 2, np.pi / 2, 80) if gx == 0 else np.linspace(np.pi / 2, 3 * np.pi / 2, 80)
        px, py = cam.proj(gx + r.arc_radius * np.cos(a0), r.arc_radius * np.sin(a0)); arc, = ax.plot(px, py, color="white", lw=lw - 1, zorder=1)
        arc.set_clip_path(Polygon(np.column_stack([X, Y]), closed=True, fc="none", ec="none", transform=ax.transData))
    for gx0, gy0, gw, gh in ln["goal_squares"]:
        px, py = cam.proj([gx0, gx0 + gw, gx0 + gw, gx0, gx0], [gy0, gy0, gy0 + gh, gy0 + gh, gy0]); ax.plot(px, py, color="white", lw=lw - 1, zorder=1)
    post_h = 8.0 if cam.on else 0.0                                            # real metres: goal posts 8 m, behind posts 5 m
    for gx, d in ((0.0, -3.0), (r.length, 3.0)):
        for yy, w, h in ((-r.goal_half_width, 4, post_h), (r.goal_half_width, 4, post_h), (-r.behind_half_width, 3, post_h * 0.62), (r.behind_half_width, 3, post_h * 0.62)):
            px, py = cam.proj([gx, gx + d], [yy, yy])
            if cam.on:
                ax.plot([px[0], px[0]], [py[0], py[0] + h * cam.scale(yy)], color="#fff8e1", lw=w, zorder=1.5, solid_capstyle="butt")
            else:
                ax.plot(px, py, color="#fff8e1" if retro else "white", lw=w, zorder=1, solid_capstyle="butt")
    (x0, x1), (y0, y1) = cam.limits()
    if retro and cam.on:                                                       # the stands: pixel crowd behind and beside the oval
        artists["crowd"] = ax.imshow(sprites.crowd(2048, 320), extent=(x0 - 200, x1 + 200, y0, y1), interpolation="nearest", zorder=-1, aspect="auto")
        artists["crowd_bright"] = sprites.crowd(2048, 320, bright=True); artists["crowd_plain"] = sprites.crowd(2048, 320)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    return artists


# ----------------------------------------------------------------------------- what the log tells us
def team_names(ep: dict, override_a=None, override_b=None) -> dict:
    names = {}
    packs = ep["meta"].get("packs") or {}
    for t in "AB":
        n = (packs.get(t) or {}).get("name")
        if not n:
            ctl = ep["meta"].get("team_" + t, "") or ""
            n = ctl[ctl.index("[") + 1:ctl.rindex("]")] if "[" in ctl and "]" in ctl else ("Team " + t)
        names[t] = n
    if override_a:
        names["A"] = override_a
    if override_b:
        names["B"] = override_b
    return names


def score_timeline(ep: dict):
    """(t, {A: (goals, behinds), B: (goals, behinds)}) after every score event, plus the opening tally. A clip cut from
    the middle of a game carries the tally at its start in ep["score_start"], so its scoreboard doesn't restart at 0-0."""
    start = ep.get("score_start") or {"A": [0, 0], "B": [0, 0]}
    tally = {t: list(start[t]) for t in ("A", "B")}; out = [(-1.0, {t: tuple(v) for t, v in tally.items()})]
    for e in ep["events"]:
        if e["type"] == "score":
            tally[e["team"]][0 if e.get("kind") == "goal" else 1] += 1
            out.append((e["t"], {t: tuple(v) for t, v in tally.items()}))
    return out


def plan_timeline(ep: dict):
    """Per team: [(t, reason, text)] whenever the coach issued a plan; for single-model teams, each new intent."""
    plans = {"A": [], "B": []}
    for d in ep["decisions"]:
        for t in "AB":
            side = d["teams"][t]; det = side.get("detail")
            if det and det.get("plan") and det.get("coach_called"):
                p = det["plan"]; txt = p["plan"]["summary"]
                plans[t].append((d["t"], p.get("reason", ""), txt))
            elif not det:
                txt = side.get("intent", "")
                if txt and (not plans[t] or plans[t][-1][2] != txt):
                    plans[t].append((d["t"], d.get("trigger", ""), txt))
    return plans


def chain_timeline(ep: dict):
    """[(t, team, text)]: the chain of possessions in the current passage, e.g. "B1 -hb-> B2 -kick-> B7 (mark) -kick-> B6".
    A turnover starts a new chain with the player who won it; a score or a centre restart clears it."""
    out = [(-1.0, None, "")]; chain = []; last_disposal = None
    for e in ep["events"]:
        k = e["type"]
        if k in ("score", "restart"):
            chain = []; last_disposal = None; out.append((e["t"], None, "")); continue
        if k == "turnover":
            chain = chain[-1:] if chain else []; last_disposal = None                       # the winner of the turnover starts the new chain
        elif k in ("possession", "mark"):
            who = e.get("by", "")
            if chain and chain[-1].startswith(who) and last_disposal is None:
                continue                                                                    # same player, no disposal in between
            tag = " (mark)" if k == "mark" else (" (%s)" % e["how"] if e.get("how") == "caught" else "")
            if chain:
                chain.append(last_disposal or "~")                                            # ~ = won on the ground / from a spill
            chain.append(who + tag); last_disposal = None
        elif k in ("kick", "handball"):
            last_disposal = "-%s->" % ("kick" if k == "kick" else "hb")
        else:
            continue
        team = chain[-1][0] if chain else None
        out.append((e["t"], team, " ".join(chain[-9:])))
    return out


def ticker_text(e: dict, names: dict) -> str:
    k = e["type"]; who = e.get("by", "")
    team = names.get(who[0], "") if who else ""
    if k == "mark":
        return "MARK  %s (%s)%s, %.0f m kick" % (who, team, " contested" if e.get("contested") else "", e.get("kick_distance", 0))
    if k == "spoil":
        return "SPOIL  %s (%s)" % (who, team)
    if k == "tackle":
        return "TACKLE  %s on %s: %s" % (who, e.get("on", ""), e.get("outcome", ""))
    if k == "free_kick":
        return "FREE KICK  %s" % who
    if k == "out_on_the_full":
        return "OUT ON THE FULL  free kick to %s" % e.get("free_kick_to", "")
    if k == "throw_in":
        return "THROW-IN"
    if k == "kick_in":
        return "KICK-IN  %s (%s)" % (who, team)
    if k == "score":
        return "%s  %s" % ("GOAL" if e.get("kind") == "goal" else "BEHIND", names.get(e.get("team", ""), ""))
    if k == "restart":
        return "CENTRE BALL-UP"
    if k == "bounce":
        return "BOUNCE  %s%s" % (who, "" if e.get("ok", True) else " FUMBLED")
    if k == "play_on":
        return "PLAY ON  %s" % who
    if k == "set_play":
        return "SET PLAY  %s, %s on the mark" % (e.get("taker", ""), e.get("man_on_mark") or "nobody")
    return k.upper()


def _fmt_score(gb):
    g, b = gb
    return "%d.%d (%d)" % (g, b, 6 * g + b)



def build_schedule(ep: dict, fps: int, goal_hold_s=2.5, behind_hold_s=1.0, fulltime_hold_s=3.0, annotations=None):
    """The video frame list: every stored frame once, plus freeze-frames for celebrations, annotations and full time.
    Each entry is (frame index, overlay or None); the overlay carries the event time it celebrates."""
    frames = ep["frames"]
    schedule = []
    score_events = [e for e in ep["events"] if e["type"] == "score"]
    notes = sorted([a for a in (annotations or []) if a.get("hold", 0) > 0], key=lambda a: a["t"])
    si = 0; ni = 0
    for i, f in enumerate(frames):
        schedule.append((i, None))
        while ni < len(notes) and notes[ni]["t"] <= f["t"] + 1e-9:          # an annotation with a hold: freeze this frame
            a = notes[ni]; ni += 1; n = int(a["hold"] * fps)
            for k in range(n):
                schedule.append((i, {"kind": "note", "ann": a, "k": k, "n": n, "t": a["t"]}))
        while si < len(score_events) and score_events[si]["t"] <= f["t"] + 1e-9:
            e = score_events[si]; si += 1
            hold = goal_hold_s if e.get("kind") == "goal" else behind_hold_s
            for k in range(int(hold * fps)):                          # freeze the frame before the restart, ball on the line
                schedule.append((max(i - 1, 0), {"kind": e.get("kind", "goal"), "team": e["team"], "k": k, "n": int(hold * fps), "t": e["t"]}))
    for k in range(int(fulltime_hold_s * fps)):
        schedule.append((len(frames) - 1, {"kind": "fulltime", "team": None, "k": k, "n": int(fulltime_hold_s * fps), "t": frames[-1]["t"]}))
    return schedule


def video_time_of_events(ep: dict, fps: int, speed=2.0, **holds):
    """Map every logged event to the second of the rendered video at which it is shown, given the freeze-frames.
    Scores map to the start of their celebration hold; everything else to the first frame at or after its time."""
    schedule = build_schedule(ep, fps, **holds)
    frames = ep["frames"]
    frame_t = [frames[i]["t"] for i, _ in schedule]
    first_video_index = {}
    for k, (i, ov) in enumerate(schedule):
        if ov is None:
            first_video_index.setdefault(round(frames[i]["t"], 3), k)
    hold_index = {}
    for k, (i, ov) in enumerate(schedule):
        if ov is not None and ov["kind"] in ("goal", "behind"):
            hold_index.setdefault((ov["kind"], ov["team"], round(ov["t"], 3)), k)
    out = []
    import bisect
    plain_times = sorted(first_video_index)
    for e in ep["events"]:
        t = e["t"]
        if e["type"] == "score":
            k = hold_index.get((e.get("kind", "goal"), e["team"], round(t, 3)))
        else:
            j = bisect.bisect_left(plain_times, t - 1e-6)
            k = first_video_index[plain_times[min(j, len(plain_times) - 1)]]
        if k is not None:
            out.append((k / fps, e))
    fulltime_k = next((k for k, (i, ov) in enumerate(schedule) if ov is not None and ov["kind"] == "fulltime"), len(schedule) - 1)
    return out, len(schedule) / fps, fulltime_k / fps


# ----------------------------------------------------------------------------- the animation
ARCHETYPE_TAGS = {"ruck": "R", "inside_mid": "IM", "outside_mid": "OM", "tall_forward": "TF", "small_forward": "SF",
                  "key_back": "KB", "running_back": "RB"}


def player_tags(meta: dict) -> dict:
    """Each player's label: shirt number + the archetype (afl18: 13TF) or the role's first letter (afl8: 7f)."""
    arch = meta.get("archetypes") or {}; roles = meta.get("roles") or {}
    return {pid: pid[1:] + (ARCHETYPE_TAGS.get(arch.get(pid), "") or roles.get(pid, "")[:1]) for pid in roles}


def animate(ep: dict, speed=2.0, save=None, name_a=None, name_b=None, goal_hold_s=2.5, behind_hold_s=1.0, fulltime_hold_s=3.0, style="retro", preview_t=None, view=60.0, values=None, team_energy=False, annotations=None):
    """preview_t: render only the frame at that game time (seconds) to `save` as a PNG, for checking the look quickly.
    view: metres of ground across the picture in the retro perspective; the camera pans along the ground to follow the ball.
    values: optional [[game_time, P(team A scores the next goal)], ...] - drawn as a live bar under the ground, centred
    at 0.5, growing right (team A, which attacks the right goal) or left (team B).
    team_energy: draw a strip under the ground with each team's average energy, live.
    annotations: analyst's marks on the footage, a list of dicts:
      {"t": 47.0, "hold": 4.0, "until": 55.0, "title": "...", "caption": "...",
       "circles": [{"player": "A7", "r": 6, "color": "#ffee00", "label": "f2"}],          # or {"x": .., "y": ..}
       "arrows":  [{"from": [x, y] | "player", "to": [x, y] | "player", "color": "#fff", "label": "..."}],
       "zones":   [{"x": [x0, x1], "y": [y0, y1], "color": "#ff5252", "label": "..."}]}
    `hold` freezes the picture at t for that many seconds with the marks shown; `until` keeps the marks (following
    the players) while play runs on to that time. Either or both."""
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    from matplotlib.patches import FancyBboxPatch
    retro = style in ("retro", "flat"); cam_on = style == "retro"
    r = Rules.from_log(ep["meta"]["rules"])
    cam = Camera(r, on=cam_on)
    frames = ep["frames"]; names = team_names(ep, name_a, name_b)
    fps = int(round(speed / r.replay_sample_dt))
    scores = score_timeline(ep); plans = plan_timeline(ep); chains = chain_timeline(ep); chain_times = np.array([c[0] for c in chains])
    events = [e for e in ep["events"] if e["type"] in TICKER_EVENTS]
    packs = ep["meta"].get("packs") or {}

    schedule = build_schedule(ep, fps, goal_hold_s, behind_hold_s, fulltime_hold_s, annotations)
    live_notes = [a for a in (annotations or []) if a.get("until") is not None]

    # ---- figure and panels
    bg = "#101018" if retro else "#0d0d0d"
    fig = plt.figure(figsize=(12.8, 7.2), facecolor=bg)
    ax_top = fig.add_axes([0.0, 0.87, 1.0, 0.13], zorder=2); ax_top.set_xlim(0, 1); ax_top.set_ylim(0, 1); ax_top.axis("off")
    ax_l = fig.add_axes([0.0, 0.075, 0.19, 0.795]); ax_r = fig.add_axes([0.81, 0.075, 0.19, 0.795])
    strip_h = 0.078
    n_strips = (1 if values else 0) + (1 if team_energy else 0)
    g_bot = 0.077 + n_strips * strip_h if n_strips else 0.075                  # each overlay takes a strip under the ground
    g_h = 0.87 - g_bot
    ax = fig.add_axes([0.19, g_bot, 0.62, g_h])
    ax_px_w, ax_px_h = 12.8 * 0.62 * 100, 7.2 * g_h * 100
    if cam_on:                                                                  # frame the camera to the panel: the view is `view` m wide
        V = view; yrange = V * ax_px_h / ax_px_w
        cam.H = 0.80 * yrange; cam.ylim = (-cam.H / 2 - 2.0, -cam.H / 2 - 2.0 + yrange)
    else:
        V = r.length + 12
    ppm = ax_px_w / V                                                            # screen pixels per metre at the near touchline
    ground = draw_ground(ax, r, cam, retro)
    ax_bot = fig.add_axes([0.19, 0.0, 0.62, 0.075]); ax_bot.set_xlim(0, 1); ax_bot.set_ylim(0, 1); ax_bot.axis("off")

    # ---- live team energy: each side's average energy (1 = fresh), straight from the recorded frames
    ebar = None
    if team_energy:
        from matplotlib.patches import Rectangle
        y0 = 0.077 + (strip_h if values else 0.0)
        ax_en = fig.add_axes([0.19, y0, 0.62, strip_h - 0.006], zorder=5)
        ax_en.set_xlim(0, 1); ax_en.set_ylim(0, 1); ax_en.axis("off")
        ax_en.add_patch(Rectangle((0, 0), 1, 1, facecolor="#16161f", edgecolor="#3a3a52", lw=1.0, zorder=1))
        ax_en.text(0.5, 0.86, "TEAM ENERGY  (average, 1 = fresh)", color="#9aa0b5", fontsize=7, family=MONO, ha="center", va="center", zorder=6)
        rows = {}
        for team, yc in (("A", 0.56), ("B", 0.22)):
            ax_en.text(0.012, yc, names[team][:12], color=COL[team], fontsize=8, family=MONO, ha="left", va="center", zorder=6)
            ax_en.add_patch(Rectangle((0.17, yc - 0.11), 0.72, 0.22, facecolor="#2a2a3a", edgecolor="none", zorder=2))
            bar = Rectangle((0.17, yc - 0.11), 0.72, 0.22, facecolor=COL[team], edgecolor="none", zorder=3)
            ax_en.add_patch(bar)
            txt = ax_en.text(0.985, yc, "", color="#ffffff", fontsize=8.5, family=MONO, ha="right", va="center", zorder=6)
            rows[team] = (bar, txt)
        for frac in (0.25, 0.5, 0.75):
            ax_en.plot([0.17 + 0.72 * frac] * 2, [0.08, 0.70], color="#ffffff", alpha=0.18, lw=0.8, zorder=4)
        ebar = rows

    # ---- live value bar: the learned next-goal probability, centred at 0.5
    vbar = None
    if values:
        from matplotlib.patches import Rectangle
        vt = np.array([float(v[0]) for v in values]); vv = np.array([float(v[1]) for v in values])
        ax_val = fig.add_axes([0.19, 0.077, 0.62, 0.072], zorder=5)
        ax_val.set_xlim(-0.5, 0.5); ax_val.set_ylim(0, 1); ax_val.axis("off")
        ax_val.add_patch(Rectangle((-0.5, 0.0), 1.0, 1.0, facecolor="#16161f", edgecolor="#3a3a52", lw=1.0, zorder=1))
        # top row: the two directions and what the bar means, well clear of the bar itself
        ax_val.text(-0.492, 0.82, "<< %s" % names["B"][:13], color=COL["B"], fontsize=8, family=MONO, ha="left", va="center", zorder=6)
        ax_val.text(0.492, 0.82, "%s >>" % names["A"][:13], color=COL["A"], fontsize=8, family=MONO, ha="right", va="center", zorder=6)
        ax_val.text(0.0, 0.82, "LEARNED VALUE - who scores the next goal", color="#9aa0b5", fontsize=7, family=MONO, ha="center", va="center", zorder=6)
        for frac in (0.1, 0.2, 0.3, 0.4, 0.5):                                  # a gridline every 10 % of probability
            for sgn in (-1, 1):
                ax_val.plot([sgn * frac, sgn * frac], [0.10, 0.58], color="#ffffff", alpha=0.16, lw=0.8, zorder=2)
        rect = Rectangle((0.0, 0.14), 0.0, 0.40, facecolor=COL["A"], edgecolor="none", zorder=3)
        ax_val.add_patch(rect)
        ax_val.plot([0, 0], [0.06, 0.62], color="#ffffff", lw=1.6, zorder=4)     # the 0.5 centre line
        vtxt = ax_val.text(0.0, 0.34, "", color="#ffffff", fontsize=9, family=MONO, ha="left", va="center", zorder=7)
        vbar = {"t": vt, "v": vv, "rect": rect, "txt": vtxt}
    for a in (ax_l, ax_r):
        a.set_xlim(0, 1); a.set_ylim(0, 1); a.axis("off")
    fig.patches.append(FancyBboxPatch((0.005, 0.885), 0.99, 0.105, boxstyle="round,pad=0.005" if not retro else "square,pad=0.003",
                                      fc="#1a1a1a" if not retro else "#000000", ec="#444" if not retro else "#ffd600", lw=1 if not retro else 2,
                                      transform=fig.transFigure, zorder=-1))

    # scoreboard
    fam = MONO if retro else None
    ax_top.text(0.03, 0.62, names["A"].upper(), color=COL["A"], fontsize=20, fontweight="bold", ha="left", va="center", family=fam)
    ax_top.text(0.97, 0.62, names["B"].upper(), color=COL["B"], fontsize=20, fontweight="bold", ha="right", va="center", family=fam)
    led = "#ffd600" if retro else "white"
    sc_a = ax_top.text(0.40, 0.62, "", color=led, fontsize=26, fontweight="bold", ha="right", va="center", family=MONO)
    sc_b = ax_top.text(0.60, 0.62, "", color=led, fontsize=26, fontweight="bold", ha="left", va="center", family=MONO)
    ax_top.text(0.50, 0.62, "-", color="#888", fontsize=22, ha="center", va="center", family=MONO)
    clock = ax_top.text(0.50, 0.15, "", color=led, fontsize=12, ha="center", va="center", family=MONO)
    ax_top.text(0.03, 0.18, "defends the left goal", color="#999", fontsize=8, ha="left", va="center", family=fam)
    ax_top.text(0.97, 0.18, "defends the right goal", color="#999", fontsize=8, ha="right", va="center", family=fam)

    # coach panels
    panels = {}
    for t, a in (("A", ax_l), ("B", ax_r)):
        face = sprites.face_for_pack(packs.get(t)) if retro else None
        port = OffsetImage(sprites.coach_sprite(COL[t], face, False), zoom=5.0, interpolation="nearest")
        ab = AnnotationBbox(port, (0.5, 0.78), frameon=False, pad=0, zorder=3); a.add_artist(ab)
        a.text(0.5, 0.50, "COACH", color="#bbb", fontsize=8, ha="center", va="center", family=fam)
        a.text(0.5, 0.46, names[t], color=COL[t], fontsize=10, fontweight="bold", ha="center", va="center", family=fam)
        bubble = a.text(0.5, 0.42, "", color="#111", fontsize=7.0, ha="center", va="top",
                        bbox=dict(boxstyle="round,pad=0.5" if not retro else "square,pad=0.5", fc="white", ec=COL[t], lw=1.5), zorder=6, family=fam)
        reason = a.text(0.5, 0.005, "", color="#999", fontsize=7, ha="center", va="bottom", family=fam)
        panels[t] = {"port": port, "ab": ab, "face": face, "bubble": bubble, "reason": reason, "shown": None, "open": False}

    # energy bars under each coach: one per player, updated every frame (older logs without energy show nothing)
    from matplotlib.patches import Rectangle
    has_energy = bool(frames[0].get("energy"))
    energy_bars = {}
    roles_all = ep["meta"].get("roles", {})
    tag = player_tags(ep["meta"])
    if has_energy:
        for t, a in (("A", ax_l), ("B", ax_r)):
            pids = sorted([i for i in frames[0]["pos"] if i[0] == t], key=lambda i: int(i[1:]))
            n = len(pids); y_top, y_bot = 0.235, 0.045; dy = (y_top - y_bot) / max(n, 1); h = dy * 0.62
            fs = 6.5 if n <= 10 else max(3.6, 6.5 * 10 / n)                       # 18 a side: smaller rows
            a.add_patch(Rectangle((0.03, y_bot - 0.02), 0.94, y_top - y_bot + 0.075, fc="#000000" if retro else "#151515", ec=COL[t], lw=1.2, zorder=7))
            a.text(0.5, y_top + 0.035, "ENERGY", color="#bbb", fontsize=7.5, ha="center", va="center", family=fam, zorder=9)
            rows = {}
            for k, pid in enumerate(pids):
                y = y_top - (k + 0.5) * dy
                a.text(0.19, y, tag[pid], color="white", fontsize=fs, ha="right", va="center", family=fam, zorder=9)
                a.add_patch(Rectangle((0.22, y - h / 2), 0.72, h, fc="#2a2a2a", ec="none", zorder=8))
                bar = Rectangle((0.22, y - h / 2), 0.72, h, fc="#43a047", ec="none", zorder=9); a.add_patch(bar)
                rows[pid] = bar
            energy_bars[t] = rows
        for pnl in panels.values():
            pnl["reason"].set_position((0.5, 0.30))

    # pitch artists
    ids = list(frames[0]["pos"]); roles = ep["meta"].get("roles", {})
    players = {}
    base_zoom = (1.8 * ppm / 16.0) if cam_on else 1.7                           # a sprite is 16 px tall and a footballer 1.8 m
    ball_zoom = (0.9 * ppm / 14.0) if cam_on else 1.3                            # the ball is drawn at 0.9 m, larger than life so it reads on screen
    pan = {"x": r.length / 2}
    if retro:
        cache = {}

        def sprite(team, frame, facing, role):
            key = (team, frame, facing, role)
            if key not in cache:
                cache[key] = sprites.player_sprite(COL[team], frame, facing, role)
            return cache[key]
        for i in ids:
            oi = OffsetImage(sprite(i[0], 0, 1, roles.get(i, "")), zoom=base_zoom, interpolation="nearest")
            ab = AnnotationBbox(oi, (0, 0), frameon=False, pad=0, zorder=3, annotation_clip=True); ax.add_artist(ab)
            players[i] = {"oi": oi, "ab": ab, "step": 0}
        ball_imgs = [sprites.ball_sprite(a) for a in range(0, 360, 30)]
        ball_oi = OffsetImage(ball_imgs[0], zoom=1.3, interpolation="nearest"); ball_ab = AnnotationBbox(ball_oi, (0, 0), frameon=False, pad=0, zorder=4, annotation_clip=True); ax.add_artist(ball_ab)
        shadow = ax.scatter([], [], s=40, c="black", alpha=0.35, zorder=2)
        team_a = team_b = ball = None
    else:
        a_ids = [i for i in ids if i[0] == "A"]; b_ids = [i for i in ids if i[0] == "B"]
        team_a = ax.scatter([], [], s=230, c=COL["A"], ec="white", lw=1.2, zorder=3); team_b = ax.scatter([], [], s=230, c=COL["B"], ec="white", lw=1.2, zorder=3)
        ball = ax.scatter([], [], s=70, c="#ffd600", ec="k", zorder=4); shadow = None
    tags = player_tags(ep["meta"])
    labels = {i: ax.text(0, 0, tags.get(i, i[1:] + roles.get(i, "")[:1]), color="white", fontsize=6.5 if retro else 7, fontweight="bold", ha="center", va="center", zorder=5, family=fam,
                         bbox=dict(boxstyle="square,pad=0.1", fc=COL[i[0]], ec="none", alpha=0.85) if retro else None, clip_on=True) for i in ids}
    ring = ax.scatter([], [], s=520, fc="none", ec="yellow", lw=2, zorder=2.5)
    mom = ax.scatter([], [], s=520, fc="none", ec="white", lw=2, ls="--", zorder=2.5)
    traj, = ax.plot([], [], "--", color="#ffd600", lw=1.5, zorder=2.5)
    overlay_box = ax.text(0.5, 0.56, "", fontsize=54, fontweight="bold", ha="center", va="center", zorder=10, family=fam, transform=ax.transAxes,
                          bbox=dict(boxstyle="square,pad=0.6" if retro else "round,pad=0.6", fc="#000000", alpha=0.8, ec=led, lw=3))
    overlay_sub = ax.text(0.5, 0.30, "", fontsize=16, color="white", ha="center", va="center", zorder=11, family=fam, transform=ax.transAxes)
    overlay_box.set_visible(False); overlay_sub.set_visible(False)
    note_title = ax.text(0.5, 0.955, "", fontsize=15, fontweight="bold", color="white", ha="center", va="top", zorder=12, transform=ax.transAxes,
                         bbox=dict(boxstyle="round,pad=0.5", facecolor="#101018", alpha=0.85, edgecolor="#ffee00", lw=1.5))
    note_cap = ax.text(0.5, 0.06, "", fontsize=11, color="white", ha="center", va="bottom", zorder=12, transform=ax.transAxes, wrap=True,
                       bbox=dict(boxstyle="round,pad=0.5", facecolor="#101018", alpha=0.85, edgecolor="#3a3a52"))
    note_title.set_visible(False); note_cap.set_visible(False)
    note_art = []                                                               # shapes drawn for the current frame, cleared every frame

    def _pt(ref, f):
        """A point from an annotation: a player id, "ball", or [x, y] in ground metres -> ground metres."""
        if isinstance(ref, str):
            return tuple(f["ball"]) if ref == "ball" else tuple(f["pos"][ref])
        return (float(ref[0]), float(ref[1]))

    def draw_note(a, f, pulse):
        from matplotlib.patches import Ellipse, FancyArrowPatch, Polygon
        for c in a.get("circles", []):
            x, y = _pt(c.get("player") or c.get("ref") or [c["x"], c["y"]], f); X, Y = cam.proj(x, y); sc = float(cam.scale(y))
            r0 = c.get("r", 6.0) * (1.0 + 0.06 * pulse)
            e = Ellipse((X, Y + 0.6 * sc), 2 * r0 * sc, 2 * r0 * sc * (0.55 if cam_on else 1.0), fill=False, lw=2.6, edgecolor=c.get("color", "#ffee00"), zorder=9)
            e.set_clip_on(True); ax.add_patch(e); note_art.append(e)
            if c.get("label"):
                t_ = ax.text(X, Y + (r0 * sc * (0.55 if cam_on else 1.0)) + 1.2 * sc, c["label"], color=c.get("color", "#ffee00"), fontsize=9, fontweight="bold",
                             ha="center", va="bottom", zorder=10, family=MONO, bbox=dict(boxstyle="round,pad=0.25", facecolor="#101018", alpha=0.75, edgecolor="none"), clip_on=True)
                note_art.append(t_)
        for ar in a.get("arrows", []):
            (x0, y0), (x1, y1) = _pt(ar["from"], f), _pt(ar["to"], f)
            X0, Y0 = cam.proj(x0, y0); X1, Y1 = cam.proj(x1, y1)
            fa = FancyArrowPatch((X0, Y0), (X1, Y1), arrowstyle="-|>", mutation_scale=18, lw=2.4, color=ar.get("color", "#ffffff"), zorder=9)
            fa.set_clip_on(True); ax.add_patch(fa); note_art.append(fa)
            if ar.get("label"):
                t_ = ax.text((X0 + X1) / 2, (Y0 + Y1) / 2 + 1.5, ar["label"], color=ar.get("color", "#ffffff"), fontsize=9, fontweight="bold", ha="center",
                             va="bottom", zorder=10, family=MONO, bbox=dict(boxstyle="round,pad=0.25", facecolor="#101018", alpha=0.75, edgecolor="none"), clip_on=True)
                note_art.append(t_)
        for z in a.get("zones", []):
            (x0, x1), (y0, y1) = z["x"], z["y"]
            corners = [cam.proj(x0, y0), cam.proj(x1, y0), cam.proj(x1, y1), cam.proj(x0, y1)]
            pg = Polygon([(float(X), float(Y)) for X, Y in corners], closed=True, facecolor=z.get("color", "#ff5252"), alpha=0.22, edgecolor=z.get("color", "#ff5252"), lw=2, zorder=8)
            pg.set_clip_on(True); ax.add_patch(pg); note_art.append(pg)
            if z.get("label"):
                X, Y = cam.proj((x0 + x1) / 2, (y0 + y1) / 2)
                t_ = ax.text(X, Y, z["label"], color="white", fontsize=9, fontweight="bold", ha="center", va="center", zorder=10, family=MONO,
                             bbox=dict(boxstyle="round,pad=0.25", facecolor=z.get("color", "#ff5252"), alpha=0.8, edgecolor="none"), clip_on=True)
                note_art.append(t_)
    ticker = ax_bot.text(0.01, 0.72, "", color="#eee", fontsize=10, ha="left", va="center", family=MONO)
    chain_lbl = ax_bot.text(0.01, 0.25, "", color="#888", fontsize=8, ha="left", va="center", family=MONO)
    chain_txt = ax_bot.text(0.115, 0.25, "", color="#eee", fontsize=9, ha="left", va="center", family=MONO)
    ev_times = np.array([e["t"] for e in events]) if events else np.array([])
    prev_pos = {i: np.array(frames[0]["pos"][i], float) for i in ids}

    def score_at(t):
        cur = scores[0][1]
        for tt, s in scores:
            if tt <= t + 1e-9:
                cur = s
        return cur

    def plan_at(team, t):
        cur = None
        for p in plans[team]:
            if p[0] <= t + 1e-9:
                cur = p
        return cur

    def update(k):
        i, ov = schedule[k]; f = frames[i]; t = f["t"]
        if ebar is not None:
            for team, (bar, txt) in ebar.items():
                e = [v for pid, v in f.get("energy", {}).items() if pid[0] == team]
                m = float(np.mean(e)) if e else 0.0
                bar.set_width(0.72 * max(min(m, 1.0), 0.0)); txt.set_text("%.2f" % m)
        if vbar is not None:
            v = float(np.interp(t, vbar["t"], vbar["v"]))                       # decisions are 1 s apart: interpolate for smooth motion
            d = v - 0.5
            vbar["rect"].set_x(min(d, 0.0)); vbar["rect"].set_width(abs(d))
            vbar["rect"].set_facecolor(COL["A"] if d >= 0 else COL["B"])
            pct = "%.0f%%" % (100 * max(v, 1 - v))
            inside = abs(d) > 0.13                                              # long fill: write inside it; short fill: just past its end
            if d >= 0:
                vbar["txt"].set_x(d - 0.015 if inside else d + 0.015); vbar["txt"].set_ha("right" if inside else "left")
            else:
                vbar["txt"].set_x(d + 0.015 if inside else d - 0.015); vbar["txt"].set_ha("left" if inside else "right")
            vbar["txt"].set_text(pct)
            vbar["txt"].set_color("#ffffff" if inside else (COL["A"] if d >= 0 else COL["B"]))
        if cam_on:                                                              # pan: ease the window toward the ball, clamped at the ends
            bxp, _ = cam.proj(f["ball"][0], f["ball"][1])
            focus = [bxp]
            notes_now = [ov["ann"]] if (ov and ov["kind"] == "note") else []       # only a frozen note pulls the camera; live marks follow the play
            for a in notes_now:
                for c in a.get("circles", []):
                    x, y = _pt(c.get("player") or c.get("ref") or [c["x"], c["y"]], f); focus.append(float(cam.proj(x, y)[0]))
                for ar in a.get("arrows", []):
                    for ref in (ar["from"], ar["to"]):
                        x, y = _pt(ref, f); focus.append(float(cam.proj(x, y)[0]))
                for z in a.get("zones", []):
                    focus += [float(cam.proj(z["x"][0], 0)[0]), float(cam.proj(z["x"][1], 0)[0])]
            target = float(np.clip((min(focus) + max(focus)) / 2 if notes_now else bxp, V / 2 - 14, r.length - V / 2 + 14))
            rate = 0.12 if ov is None else (1.0 if (ov["kind"] == "note" and ov["k"] == 0) else 0.0)   # a hold snaps to its marks
            pan["x"] += (target - pan["x"]) * rate
            ax.set_xlim(pan["x"] - V / 2, pan["x"] + V / 2)
            if "crowd" in ground:
                ground["crowd"].set_data(ground["crowd_bright"] if (ov and ov["kind"] == "goal" and (k // 3) % 2 == 0) else ground["crowd_plain"])
        if retro:
            for j, pl in players.items():
                pos = np.array(f["pos"][j], float); v = pos - prev_pos[j]; prev_pos[j] = pos
                moving = np.linalg.norm(v) > 0.08 and ov is None
                if moving:
                    pl["step"] += 1
                facing = 1 if v[0] >= 0 else -1
                pl["oi"].set_data(sprite(j[0], (pl["step"] // 3) % 2 if moving else 0, facing, roles.get(j, "")))
                sc = float(cam.scale(pos[1])); X, Y = cam.proj(pos[0], pos[1])
                pl["oi"].set_zoom(base_zoom * sc)
                lift = (0.9 if cam_on else 2.2) * sc                                          # the sprite is centred: put the feet on the spot
                pl["ab"].xy = (X, Y + lift); pl["ab"].xybox = (X, Y + lift)
                pl["ab"].set_zorder(3.0 + (1.0 - cam.depth(pos[1])) * 0.5)                  # nearer players draw on top
                labels[j].set_position((X, Y + (2.6 if cam_on else 6.5) * sc)); labels[j].set_fontsize(6.5 * (0.6 + 0.4 * sc) if cam_on else 6.5)
            bx, by = f["ball"]; h = f.get("height", 0.0); sc = float(cam.scale(by)); X, Y = cam.proj(bx, by)
            ang = (k * 30) % 360 if f["state"] == "flight" else 0
            ball_oi.set_data(ball_imgs[ang // 30]); ball_oi.set_zoom(ball_zoom * (1.0 + 0.12 * h) * sc)
            lift = ((0.45 + 0.9 * h) if cam_on else (0.8 + 0.9 * h)) * sc
            ball_ab.xy = (X, Y + lift); ball_ab.xybox = ball_ab.xy; ball_ab.set_zorder(4.0 + (1.0 - cam.depth(by)) * 0.5)
            shadow.set_offsets([[X, Y]]); shadow.set_sizes([(0.7 * ppm * sc * 0.72) ** 2 if cam_on else 40 * sc * sc])
        else:
            team_a.set_offsets([f["pos"][j] for j in a_ids]); team_b.set_offsets([f["pos"][j] for j in b_ids])
            for j, lab in labels.items():
                lab.set_position(f["pos"][j])
            ball.set_offsets([f["ball"]]); ball.set_sizes([70 + 50 * f.get("height", 0.0)])
        if f["holder"]:
            hp = f["pos"][f["holder"]]; X, Y = cam.proj(hp[0], hp[1]); sc = float(cam.scale(hp[1]))
            ring.set_offsets([[X, Y]]); ring.set_sizes([(2.6 * ppm * sc * 0.72) ** 2 if cam_on else 520 * sc * sc]); ring.set_edgecolor("lime" if f["protected"] else "yellow")
        else:
            ring.set_offsets(np.empty((0, 2)))
        m = f.get("man_on_mark")
        if m:
            mp = f["pos"][m]; X, Y = cam.proj(mp[0], mp[1]); scm = float(cam.scale(mp[1])); mom.set_offsets([[X, Y]]); mom.set_sizes([(2.6 * ppm * scm * 0.72) ** 2 if cam_on else 520 * scm * scm])
        else:
            mom.set_offsets(np.empty((0, 2)))
        if f["landing"] and f["state"] == "flight":
            px, py = cam.proj([f["ball"][0], f["landing"][0]], [f["ball"][1], f["landing"][1]]); traj.set_data(px, py)
        else:
            traj.set_data([], [])
        s = score_at(ov["t"] if ov and ov.get("t") is not None else t)      # a celebration shows the score it just produced
        sc_a.set_text(_fmt_score(s["A"])); sc_b.set_text(_fmt_score(s["B"]))
        clock.set_text("%02d:%04.1f" % (int(t // 60), t % 60) + ("   FULL TIME" if ov and ov["kind"] == "fulltime" else ""))
        # energy bars
        if has_energy:
            en = f.get("energy", {})
            for team, rows in energy_bars.items():
                for pid, bar in rows.items():
                    e_val = float(en.get(pid, 1.0))
                    bar.set_width(0.72 * max(0.0, min(1.0, e_val)))
                    bar.set_facecolor("#43a047" if e_val > 0.6 else "#ffb300" if e_val > 0.35 else "#e53935")
        # coach panels: latest plan; the portrait 'talks' for 3 s of play after a new plan
        for team, pnl in panels.items():
            p = plan_at(team, t)
            if p is not None and pnl["shown"] is not p:
                pnl["shown"] = p
                pnl["bubble"].set_text(textwrap.fill(p[2], 34)[:(520 if has_energy else 900)])
                pnl["reason"].set_text("plan at %02d:%04.1f (%s)" % (int(p[0] // 60), p[0] % 60, p[1]))
            talking = p is not None and t - p[0] < 3.0
            open_now = talking and (k // 2) % 2 == 0
            if open_now != pnl["open"]:
                pnl["open"] = open_now
                pnl["port"].set_data(sprites.coach_sprite(COL[team], pnl["face"], open_now))
                pnl["ab"].xybox = (0.5, 0.78 + (0.008 if open_now else 0.0)); pnl["ab"].xy = pnl["ab"].xybox
            pnl["bubble"].get_bbox_patch().set_linewidth(3.0 if talking else 1.5)
        # tickers
        if ov and ov["kind"] in ("goal", "behind"):
            ticker.set_text("%s  %s" % ("GOAL" if ov["kind"] == "goal" else "BEHIND", names[ov["team"]]))
        elif len(ev_times):
            j = int(np.searchsorted(ev_times, t + 1e-9) - 1)
            ticker.set_text(ticker_text(events[j], names) if j >= 0 and t - ev_times[j] <= 4.0 else "")
        ci = int(np.searchsorted(chain_times, t + 1e-9) - 1); ct = chains[max(ci, 0)]
        chain_lbl.set_text("POSSESSION" if ct[2] else ""); chain_txt.set_text(ct[2][-118:]); chain_txt.set_color(COL[ct[1]] if ct[1] else "#eee")
        # analyst's annotations: a frozen note, and any live marks whose window covers this moment
        for art in note_art:
            art.remove()
        note_art.clear()
        active = []
        if ov and ov["kind"] == "note":
            active.append(ov["ann"])
        active += [a for a in live_notes if a["t"] - 1e-6 <= t <= a["until"] + 1e-6 and not (ov and ov["kind"] == "note" and ov["ann"] is a)]
        if active:
            pulse = np.sin(k * 0.5)
            for a in active:
                draw_note(a, f, pulse)
            a0 = active[0]
            note_title.set_text(a0.get("title", "")); note_title.set_visible(bool(a0.get("title")))
            note_cap.set_text(a0.get("caption", "")); note_cap.set_visible(bool(a0.get("caption")))
        else:
            note_title.set_visible(False); note_cap.set_visible(False)
        # overlays
        if ov and ov["kind"] in ("goal", "behind"):
            tm = ov["team"]; pulse = 1.0 + 0.08 * np.sin(ov["k"] / max(ov["n"], 1) * np.pi * 4)
            overlay_box.set_text("G O A L ! ! !" if ov["kind"] == "goal" else "BEHIND"); overlay_box.set_color(COL[tm]); overlay_box.set_fontsize((54 if ov["kind"] == "goal" else 30) * pulse)
            overlay_sub.set_text("%s   %s - %s" % (names[tm].upper(), _fmt_score(s["A"]), _fmt_score(s["B"])))
            overlay_box.set_visible(True); overlay_sub.set_visible(True)
        elif ov and ov["kind"] == "fulltime":
            pa, pb = 6 * s["A"][0] + s["A"][1], 6 * s["B"][0] + s["B"][1]
            lead = "DRAW" if pa == pb else ("%s WIN" % (names["A"] if pa > pb else names["B"]).upper())
            overlay_box.set_text("FULL TIME"); overlay_box.set_color("white"); overlay_box.set_fontsize(40)
            overlay_sub.set_text("%s   %s - %s" % (lead, _fmt_score(s["A"]), _fmt_score(s["B"])))
            overlay_box.set_visible(True); overlay_sub.set_visible(True)
        else:
            overlay_box.set_visible(False); overlay_sub.set_visible(False)
        return ()

    if preview_t is not None:
        k = next((kk for kk, (ii, ov) in enumerate(schedule) if frames[ii]["t"] >= preview_t - 1e-9), len(schedule) - 1)
        while k + 1 < len(schedule) and schedule[k + 1][1] is not None and schedule[k + 1][1]["kind"] == "note":
            k += 1                                                                          # land on the frozen, annotated frame
        for kk in range(max(0, k - 6), k + 1):                                          # a few frames so run cycles and talking states settle
            update(kk)
        fig.savefig(save, dpi=100, facecolor=fig.get_facecolor()); plt.close(fig)
        return None
    anim = FuncAnimation(fig, update, frames=len(schedule), interval=1000 / fps, blit=False, repeat=False)
    if save:
        if save.lower().endswith(".mp4"):
            from matplotlib.animation import FFMpegWriter
            anim.save(save, writer=FFMpegWriter(fps=fps, codec="libx264", extra_args=["-crf", "27", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]), dpi=100)   # ~8 MB per 2-min game, under the 30 MB share limit
        else:
            anim.save(save, writer="pillow", fps=fps, dpi=80)
        plt.close(fig)
    else:
        plt.show()
    return anim


def main(argv=None):
    ap = argparse.ArgumentParser(description="Replay a saved episode as a retro broadcast-style video")
    ap.add_argument("path"); ap.add_argument("--speed", type=float, default=2.0)
    ap.add_argument("--gif", default=None, help="output file: .mp4 (H.264 via ffmpeg, the shareable option) or .gif")
    ap.add_argument("--name-a", default=None, help="display name for team A (default: the team pack's name)")
    ap.add_argument("--name-b", default=None)
    ap.add_argument("--view", type=float, default=60.0, help="retro: metres of ground across the picture (the camera pans with the ball)")
    ap.add_argument("--preview", type=float, default=None, help="render a single frame at this game time to --gif (as a PNG) instead of the video")
    ap.add_argument("--style", default="retro", choices=["retro", "flat", "classic"], help="retro = 16-bit perspective with sprites (default); flat = sprites from above; classic = discs")
    ap.add_argument("--values", default=None, help="JSON file: [[game_time, P(A scores next goal)], ...] - drawn as a live bar")
    ap.add_argument("--team-energy", action="store_true", help="draw each team's average energy as a live strip under the ground")
    ap.add_argument("--annotations", default=None, help="JSON file with a list of annotations (see animate)")
    a = ap.parse_args(argv)
    values = None
    if a.values:
        import json
        values = json.load(open(a.values, encoding="utf-8"))
        values = values["series"] if isinstance(values, dict) else values
    ann = json.load(open(a.annotations, encoding="utf-8")) if a.annotations else None
    animate(load_episode(a.path), a.speed, a.gif, a.name_a, a.name_b, style=a.style, preview_t=a.preview, view=a.view, values=values, team_energy=a.team_energy, annotations=ann)


if __name__ == "__main__":
    main()
