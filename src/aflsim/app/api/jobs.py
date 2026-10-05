"""JOBS: start an action (match, tournament, rate, render, check), follow its log, cancel it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from aflsim.app import services as S

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobRequest(BaseModel):
    kind: str
    params: dict


@router.get("")
def list_jobs(request: Request, limit: int = 30):
    jm = request.app.state.jobs
    out = jm.list(limit)
    for j in out:                                                          # jobs saved before outputs listed videos
        if j["status"] != "running" and "videos" not in (j.get("outputs") or {}):
            j["outputs"] = jm.parse_outputs(jm.log(j["id"], tail_bytes=2_000_000))
    return out


@router.post("")
def start(request: Request, req: JobRequest):
    build = S.JOB_KINDS.get(req.kind)
    if build is None:
        raise HTTPException(400, "unknown job kind %r (have: %s)" % (req.kind, ", ".join(S.JOB_KINDS)))
    try:
        argv, title, uses_llm = build(req.params)
    except (KeyError, ValueError, FileNotFoundError, PermissionError) as e:
        raise HTTPException(400, "%s: %s" % (type(e).__name__, e))
    try:
        job = request.app.state.jobs.start(req.kind, S.ctx_title(title), S.ctx_argv(argv), uses_llm, meta=dict(req.params, context="%s.%d" % (S.game(), S.engine())))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    S.invalidate()
    return job


@router.get("/{jid}")
def get(request: Request, jid: str, tail: int = 60000):
    j = request.app.state.jobs.get(jid)
    if j is None:
        raise HTTPException(404, "no job %s" % jid)
    j["log"] = request.app.state.jobs.log(jid, tail)
    if j["status"] == "running":
        j["outputs"] = request.app.state.jobs.parse_outputs(j["log"])
    return j


@router.post("/{jid}/cancel")
def cancel(request: Request, jid: str):
    j = request.app.state.jobs.cancel(jid)
    if j is None:
        raise HTTPException(404, "no job %s" % jid)
    return j
