"""The retro broadcast replay (replay.py) as data, for the browser's live view: everything replay.animate derives from
a game log (names, scores, coach plans, the possession chain, the ticker, energy, the ground's lines) plus its pixel
sprites as PNG data URLs, so the browser draws exactly what the videos show, at 60 frames a second."""
from __future__ import annotations

import base64
import io

import numpy as np

from ..config import Rules
from ..ground import Oval
from . import sprites
from .replay import COL, TICKER_EVENTS, chain_timeline, plan_timeline, player_tags, score_timeline, team_names, ticker_text

VERSION = 1
ROLES = ("midfielder", "defender", "forward", "")


def _png(arr) -> str:
    from PIL import Image
    a = np.asarray(arr, dtype=np.uint8)
    im = Image.fromarray(a, "RGBA" if a.shape[-1] == 4 else "RGB")
    buf = io.BytesIO(); im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def sprite_sheet(faces: dict | None = None) -> dict:
    """The replay's sprites: players by team / run frame / facing / role, the ball's 12 spin angles, the coaches with
    the mouth shut and open, and the crowd (plain, and bright for a goal)."""
    faces = faces or {}
    players = {t: {"%d_%d_%s" % (fr, fa, role): _png(sprites.player_sprite(COL[t], fr, fa, role))
                   for fr in (0, 1) for fa in (1, -1) for role in ROLES} for t in "AB"}
    return {"players": players, "ball": [_png(sprites.ball_sprite(a)) for a in range(0, 360, 30)],
            "coach": {t: [_png(sprites.coach_sprite(COL[t], faces.get(t), m)) for m in (False, True)] for t in "AB"},
            "crowd": _png(sprites.crowd(2048, 320)), "crowd_bright": _png(sprites.crowd(2048, 320, bright=True)), "colours": COL}


def _rnd(v, n=2):
    return None if v is None else round(float(v), n)


def pack_frame(f: dict, pids: list) -> dict:
    """One snapshot, as the browser's broadcast view reads it."""
    en = f.get("energy") or {}
    return {"t": _rnd(f["t"]), "p": [_rnd(c) for pid in pids for c in f["pos"][pid]], "b": [_rnd(f["ball"][0]), _rnd(f["ball"][1])],
            "h": _rnd(f.get("height") or 0.0), "s": f.get("state", ""), "ho": f.get("holder"),
            "l": [_rnd(f["landing"][0]), _rnd(f["landing"][1])] if f.get("landing") else None, "pr": 1 if f.get("protected") else 0,
            "mm": f.get("man_on_mark"), "e": [_rnd(en.get(pid, 1.0), 3) for pid in pids] if en else None}


def ground_data(r) -> dict:
    ov = Oval(r); ln = ov.lines(); x, y = ov.outline(600)
    return {"length": r.length, "width": r.width, "outline": [[round(float(a), 2), round(float(b), 2)] for a, b in zip(x, y)],
            "centre_circle": list(ln["centre_circle"]), "centre_square": list(ln["centre_square"]), "goal_squares": [list(g) for g in ln["goal_squares"]],
            "arc_radius": r.arc_radius, "goal_half_width": r.goal_half_width, "behind_half_width": r.behind_half_width}


def broadcast_data(ep: dict, name_a=None, name_b=None) -> dict:
    r = Rules.from_log(ep["meta"]["rules"])
    frames = ep["frames"]; pids = sorted(frames[0]["pos"], key=lambda p: (p[0], int(p[1:])))
    out_frames = [pack_frame(f, pids) for f in frames]
    names = team_names(ep, name_a, name_b)
    events = [e for e in ep["events"] if e["type"] in TICKER_EVENTS]
    faces = {t: sprites.face_for_pack((ep["meta"].get("packs") or {}).get(t)) for t in "AB"}
    return {
        "version": VERSION, "names": names, "pids": pids, "roles": ep["meta"].get("roles", {}), "tags": player_tags(ep["meta"]),
        "ground": ground_data(r),
        "frames": out_frames, "duration": round(float(frames[-1]["t"]), 2),
        "scores": [[t, {k: list(v) for k, v in s.items()}] for t, s in score_timeline(ep)],
        "plans": {t: [[round(p[0], 2), p[1], p[2]] for p in plan_timeline(ep)[t]] for t in "AB"},
        "chains": [[round(c[0], 2), c[1], c[2]] for c in chain_timeline(ep)],
        "ticker": [[round(e["t"], 2), ticker_text(e, names)] for e in events],
        "scoring": [[round(e["t"], 2), e["team"], e.get("kind")] for e in ep["events"] if e["type"] == "score"],
        "actions": [[round(e["t"], 2), e["type"], e.get("by") or e.get("taker") or e.get("to")] for e in ep["events"]
                    if e["type"] in ("kick", "handball", "mark", "spoil", "tackle")],
        "sprites": sprite_sheet(faces),
    }
