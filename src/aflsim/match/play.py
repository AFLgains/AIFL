"""Playing matches: a match is a job (plain data), a worker plays it, and only the coordinator writes the result.

    row = play_match("mine/my_bot", "zoo:ontario", seed=1)          # one game, stored, log saved
    jobs = series_jobs("mine/my_bot", "zoo:rules", n=20, seed0=1000)   # both ends
    for row in run_jobs(jobs, store=Store(), parallel=12): ...

Fairness is the default: player attributes are mirrored, and `series_jobs` plays every seed from both ends.
Bots are seeded as `seed` (team A) and `seed + 1000` (team B), as in the old arena, so games reproduce exactly.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import asdict, dataclass

from aflsim import paths
from aflsim.games import DEFAULT_GAME, engine_version, get_game

LIMIT_PATTERNS = re.compile(r"insufficient_quota|quota|credit|billing|rate.?limit|429|401|unauthori[sz]ed|api key", re.I)


class LLMLimitError(RuntimeError):
    """An LLM bot hit a credit, quota, auth or rate limit: the run stops cleanly instead of playing no-op turns."""


@dataclass(frozen=True)
class MatchJob:
    bot_a: str
    bot_b: str
    seed: int
    seconds: float
    game: str = DEFAULT_GAME
    max_decisions: int | None = None
    record: str = "frames"                  # "frames" (replayable) | "none" (headless: faster, smaller)
    save_log: bool = True
    tournament_id: int | None = None


def series_jobs(bot_a, bot_b, n, seed0, seconds=None, both_ends=True, **kw) -> list[MatchJob]:
    """n seeds; with both_ends each seed is also played with the bots swapped (the fair way to compare two bots)."""
    g = get_game(kw.get("game")); seconds = float(seconds or g.DEFAULT_SECONDS)
    jobs = []
    for k in range(n):
        jobs.append(MatchJob(bot_a, bot_b, seed0 + k, seconds, **kw))
        if both_ends:
            jobs.append(MatchJob(bot_b, bot_a, seed0 + k, seconds, **kw))
    return jobs


def run_job(job: MatchJob) -> dict:
    """Play one match (in any process). Returns the store row, with the log written to a temporary name."""
    import numpy as np

    from aflsim.bots.registry import load_bot
    from aflsim.engine import run_match, save_log
    g = get_game(job.game); rules = g.make_rules(job.seconds)
    a = load_bot(job.bot_a, "A", rules, job.seed, job.game); b = load_bot(job.bot_b, "B", rules, job.seed + 1000, job.game)
    ep = run_match(g, a, b, rules, job.seed, job.max_decisions, record=job.record)
    ep["meta"]["packs"] = {"A": {"name": a.spec, "motto": "", "scripted": True}, "B": {"name": b.spec, "motto": "", "scripted": True}}
    ep["meta"]["bots"] = {"A": {"spec": a.spec, "hash": a.bot_hash}, "B": {"spec": b.spec, "hash": b.bot_hash}}
    ep["meta"]["bot_errors"] = {"A": a.errors, "B": b.errors}
    st = ep["stats"]
    for side, bot in (("A", a), ("B", b)):
        from aflsim.bots.registry import is_llm
        errs = list(bot.errors) + list(getattr(bot.inner, "errors", []) or [])
        if is_llm(bot.spec) and any(LIMIT_PATTERNS.search(str(e)) for e in errs):
            raise LLMLimitError("%s (team %s) hit an API limit: %s" % (bot.spec, side, str(errs[0])[:200]))
    log_path = None
    if job.save_log:
        log_path = os.path.join(paths.logs_dir(job.game), "tmp", uuid.uuid4().hex + ".json.gz")
        save_log(ep, log_path)
    sa, sb = st["score_A"], st["score_B"]
    stats = {k: v for k, v in st.items() if k not in ("llm_errors",)}
    return {"game": job.game, "engine_version": engine_version(g), "seconds": job.seconds, "seed": job.seed,
            "bot_a": a.spec, "bot_b": b.spec, "hash_a": a.bot_hash, "hash_b": b.bot_hash, "score_a": sa, "score_b": sb,
            "outcome": 1.0 if sa > sb else 0.0 if sa < sb else 0.5, "result": st["result"], "errors_a": len(a.errors), "errors_b": len(b.errors),
            "decisions": st["decisions"], "tokens": st.get("tokens_used", 0), "wall_s": st.get("wall_s"), "max_decisions": job.max_decisions,
            "stats_json": stats, "tournament_id": job.tournament_id, "log_path": log_path, "source": "play", "numpy_version": np.__version__,
            "first_errors": {"A": a.errors[:3], "B": b.errors[:3]}}


def _file_log(store, match_id, row):
    """Give a stored match's log its permanent name: results/logs/<game>/<YYYY-MM>/<id>.json.gz."""
    tmp = row.get("log_path")
    if not tmp or not os.path.exists(tmp):
        return None
    month = row.get("created", "")[:7] or "undated"
    final = os.path.join(paths.logs_dir(row["game"]), month, "%d.json.gz" % match_id)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    os.replace(tmp, final)
    store.set_log(match_id, final)
    return final


def record(store, row: dict) -> dict:
    from aflsim.match.store import now
    row = dict(row); row["created"] = row.get("created") or now()
    mid = store.add_match(row)
    row["id"] = mid
    row["log_path"] = _file_log(store, mid, row) or row.get("log_path")
    return row


def run_jobs(jobs, store, parallel: int = 8, on_result=None, on_fail=None):
    """Play jobs, storing each result as it arrives. Games with an LLM bot run one at a time, in this process (one
    LLM run at a time, and a credit limit stops the run cleanly). Everything else runs in a process pool."""
    from aflsim.bots.registry import is_llm
    from aflsim.exec import Serial, make_executor
    llm = [j for j in jobs if is_llm(j.bot_a) or is_llm(j.bot_b)]
    code = [j for j in jobs if j not in llm]
    out = []
    for runner, js in ((make_executor(parallel), code), (Serial(), llm)):
        for row in runner.imap(run_job, js, on_fail=on_fail):
            row = record(store, row); out.append(row)
            if on_result:
                on_result(row)
    return out


def play_match(bot_a, bot_b, seed=0, seconds=None, game=DEFAULT_GAME, store=None, max_decisions=None, record_frames=True, save=True) -> dict:
    """One game, played here and now, stored (unless save=False) with its log."""
    from aflsim.match.store import Store
    g = get_game(game)
    job = MatchJob(bot_a, bot_b, int(seed), float(seconds or g.DEFAULT_SECONDS), game, max_decisions, "frames" if record_frames else "none", save_log=save)
    row = run_job(job)
    if not save:
        return row
    st = store or Store(game)
    return record(st, row)


def job_dict(job: MatchJob) -> dict:
    return asdict(job)
