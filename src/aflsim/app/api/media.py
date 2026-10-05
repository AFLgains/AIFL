"""MEDIA (public): what the retro broadcast viewer and the video export need, apart from the analysis board.
    GET  /api/analysis/sprites                the retro broadcast's sprite sheet
    GET  /api/analysis/{match}/broadcast      a match as the retro broadcast draws it (frames, names, ticker, sprites)
    POST /api/analysis/video3d/start | {id}/frames | {id}/finish    the browser renders frames, the app encodes the mp4
"""
from __future__ import annotations

import os
import re
import subprocess
import time

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/analysis", tags=["media"])


# ---- 3D videos: the browser renders the replay frame by frame (fixed 30 fps, whether or not the tab is on screen) and
# streams the frames (JPEGs) here, straight into an ffmpeg that writes the mp4 into the videos folder.
_VIDEOS3D = {}


@router.post("/video3d/start")
def video3d_start(name: str = "replay", fps: int = 30):
    from aflsim import paths
    from aflsim.app import services as S
    from aflsim.video.ffmpeg import find_ffmpeg
    ff = find_ffmpeg()
    if not ff:
        raise HTTPException(500, "ffmpeg not found: install imageio-ffmpeg in the project's environment")
    base = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:80] + time.strftime("_%H%M%S")
    out = os.path.join(paths.videos_dir(S.game()), base + ".mp4"); log = out + ".log"
    errf = open(log, "wb")
    proc = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(int(fps)), "-c:v", "mjpeg", "-i", "-",
                             "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
                             "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], stdin=subprocess.PIPE, stderr=errf)
    vid = base
    _VIDEOS3D[vid] = {"proc": proc, "out": out, "log": log, "errf": errf, "rel": base + ".mp4", "frames": 0}
    return {"id": vid}


@router.post("/video3d/{vid}/frames")
async def video3d_frames(request: Request, vid: str, n: int = 1):
    v = _VIDEOS3D.get(vid)
    if v is None:
        raise HTTPException(404, "no video %s being made" % vid)
    body = await request.body()
    try:
        v["proc"].stdin.write(body); v["proc"].stdin.flush()
    except (BrokenPipeError, OSError):
        raise HTTPException(500, "the encoder stopped: %s" % _video3d_error(v))
    v["frames"] += int(n)
    return {"frames": v["frames"]}


def _video3d_error(v) -> str:
    try:
        v["errf"].flush()
        return open(v["log"], encoding="utf-8", errors="replace").read()[-400:] or "unknown error"
    except OSError:
        return "unknown error"


@router.post("/video3d/{vid}/finish")
def video3d_finish(vid: str, cancel: bool = False):
    v = _VIDEOS3D.pop(vid, None)
    if v is None:
        raise HTTPException(404, "no video %s being made" % vid)
    try:
        v["proc"].stdin.close()
    except OSError:
        pass
    rc = v["proc"].wait(timeout=600); v["errf"].close()
    err = open(v["log"], encoding="utf-8", errors="replace").read()[-400:] if os.path.exists(v["log"]) else ""
    if os.path.exists(v["log"]):
        os.remove(v["log"])
    if cancel or rc != 0 or not v["frames"]:
        if os.path.exists(v["out"]):
            os.remove(v["out"])
        if cancel or not v["frames"]:
            return {"cancelled": True}
        raise HTTPException(500, "making the video failed: %s" % err)
    return {"rel": v["rel"], "bytes": os.path.getsize(v["out"]), "frames": v["frames"]}


_SPRITES = {}


@router.get("/sprites")
def get_sprites():
    """The retro broadcast's sprite sheet on its own (for sandbox play-outs)."""
    from aflsim.app import services as S
    from aflsim.games import get_game
    if S.game() not in _SPRITES:
        _SPRITES[S.game()] = get_game(S.game()).broadcast_sprites()
    return _SPRITES[S.game()]


@router.get("/{match_id}/broadcast")
def get_broadcast(match_id: int):
    """The match as the retro broadcast (the videos' look) draws it: frames, names, plans, chain, ticker and sprites."""
    import json
    from aflsim import paths
    from aflsim.app import services as S
    from aflsim.games import get_game
    from aflsim.match.store import Store
    from aflsim.video.render import game_log
    game = S.game(); g = get_game(game)
    d = os.path.join(paths.home(), "results", "analysis", game); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "%d_broadcast.json" % match_id)
    if os.path.exists(p):
        try:
            data = json.load(open(p, encoding="utf-8"))
            if data.get("version") == g.broadcast_version():
                return data
        except (OSError, ValueError):
            pass
    st = Store(game); row = st.match(int(match_id)); st.close()
    if row is None:
        raise HTTPException(404, "no match %d" % match_id)
    try:
        ep = game_log(row, game)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    data = g.broadcast(ep, name_a=row["bot_a"].split("/")[-1].replace("zoo:", ""), name_b=row["bot_b"].split("/")[-1].replace("zoo:", ""))
    data.update(match_id=row["id"], seconds=row["seconds"])
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


