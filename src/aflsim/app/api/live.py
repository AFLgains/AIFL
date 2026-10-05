"""LIVE: play a game yourself, in real time. The browser starts a session, then ticks it 20 times a second: it sends the
controls (direction, sprint, button presses) and gets back the new frames and events. One session at a time.
    POST /api/live/start            {opponent, helper, seconds}  -> {sid, names, pids, ground, sprites, ...}
    POST /api/live/{sid}/tick       {since, ev, input, presses}  -> {frames, events, control, notes, status}
    POST /api/live/{sid}/stop
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from aflsim.app import services as S

router = APIRouter(prefix="/api/live", tags=["live"])


def _sessions(request) -> dict:
    if not hasattr(request.app.state, "live"):
        request.app.state.live = {}
    return request.app.state.live


@router.post("/start")
def start(request: Request, params: dict):
    from aflsim.games import get_game
    try:
        opponent = S._spec(params.get("opponent") or "zoo:rules")
        helper = S._spec(params.get("helper") or "zoo:rules")
    except Exception as e:                                                  # noqa: BLE001
        raise HTTPException(400, str(e))
    if opponent.startswith("llm:") or helper.startswith("llm:"):
        raise HTTPException(400, "LLM bots are too slow to play live against")
    seconds = float(params.get("seconds") or 240)
    if not 20 <= seconds <= 1200:
        raise HTTPException(400, "seconds: 20 to 1200")
    live = _sessions(request)
    for s in live.values():                                                 # one game at a time
        s.stop()
    live.clear()
    m = get_game(S.game()).live_match(opponent=opponent, helper=helper, seconds=seconds, game_name=S.game(),
                                      names={"A": "YOU", "B": opponent.split("/")[-1].replace("zoo:", "")})
    sid = uuid.uuid4().hex[:10]
    live[sid] = m
    return {"sid": sid, "opponent": opponent, "helper": helper, **m.static()}


@router.post("/{sid}/tick")
def tick(request: Request, sid: str, body: dict):
    m = _sessions(request).get(sid)
    if m is None:
        raise HTTPException(404, "no live game %s (it ended, or another one started)" % sid)
    return m.tick(int(body.get("since", -1)), int(body.get("ev", 0)), body.get("input"), body.get("presses"))


@router.post("/{sid}/stop")
def stop(request: Request, sid: str):
    m = _sessions(request).pop(sid, None)
    if m is not None:
        m.stop()
    return {"stopped": m is not None}
