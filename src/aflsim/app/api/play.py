"""PLAY: matches, tournaments (configs and results), ratings and the ladder. Actions become jobs (see jobs.py)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aflsim.app import services as S

router = APIRouter(prefix="/api/play", tags=["play"])


class TournamentConfig(BaseModel):
    config: dict
    overwrite: bool = False


@router.get("/ladder")
def ladder(seconds: float = 240):
    return S.ladder_table(seconds)


@router.get("/ladders")
def ladders():
    return [{"seconds": s, "n": L["n"], "bots": len(L["ratings"])} for s, L in S.ladders().items()]


@router.get("/tournaments")
def tournaments():
    return S.tournaments()


@router.get("/tournaments/{tid}")
def tournament(tid: int):
    try:
        return S.tournament_detail(tid)
    except (TypeError, KeyError):
        raise HTTPException(404, "no tournament %d" % tid)


@router.get("/tournament-configs")
def configs():
    return S.tournament_configs()


@router.post("/tournament-configs")
def save_config(t: TournamentConfig):
    try:
        return {"path": S.save_tournament_config(t.config, t.overwrite)}
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(400, "unknown bot: %s" % e)
    except FileExistsError as e:
        raise HTTPException(409, str(e))
