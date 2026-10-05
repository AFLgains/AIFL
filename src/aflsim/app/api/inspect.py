"""INSPECT: stored matches (filtered by scope, tournament, bot, length, video), one match in detail (stats, events,
videos), and the video library."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aflsim.app import services as S

router = APIRouter(prefix="/api/inspect", tags=["inspect"])


@router.get("/matches")
def matches(bot: str | None = None, tournament: int | None = None, scope: str = "all", seconds: float | None = None,
            has_video: bool = False, limit: int = 200, offset: int = 0, engine_version: int | None = None):
    try:
        return S.matches(bot, tournament, scope, seconds, has_video, limit, offset, engine_version)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/filters")
def filters():
    return S.filter_options()


@router.get("/matches/{mid}")
def match(mid: int):
    r = S.match_detail(mid)
    if r is None:
        raise HTTPException(404, "no match %d" % mid)
    return r


@router.get("/matches/{mid}/events")
def events(mid: int):
    """The match's event list (kicks, marks, tackles, scores...) from its log, if it has one."""
    import os

    from aflsim.engine import load_log
    r = S.match_detail(mid)
    if r is None:
        raise HTTPException(404, "no match %d" % mid)
    if not (r.get("log_path") and os.path.exists(r["log_path"])):
        return {"events": [], "note": "no stored log (code-bot games are re-simulated when rendered)"}
    return {"events": load_log(r["log_path"])["events"]}


@router.get("/videos")
def videos():
    return S.videos()
