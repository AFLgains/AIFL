"""Tournaments from a TOML file. Every pairing plays `seeds` seeds, each from BOTH ends (fair), and every game lands
in the central store tagged with the tournament, so a stopped tournament resumes by skipping what is already played.

    name = "weekend_cup"            # unique: re-running the same name resumes it
    format = "round_robin"          # round_robin | groups | gauntlet | ladder
    seconds = 240
    seeds = 5                       # per pairing; x2 for both ends
    seed = 100000                   # base seed (each pairing derives its own from the two names)
    logs = false                    # keep full game logs (videos without re-simulating); LLM games always keep theirs
    bots = ["mine/my_bot", "mine/other_bot", "zoo:rules", "zoo:ontario"]

    # format = "groups":   [groups] A = [...] B = [...]   and   finals = 2  (top 2 of each group play a final round robin)
    # format = "gauntlet": challenger = "<spec>"  and  field = [...]  (or field = "library")
    # format = "ladder":   bots = "library" (every bot in the library) or a list; the result is a rating ladder

Standings are AFL-style: 4 premiership points a win, 2 a draw, then percentage (points for / points against x 100).
Ratings (Bradley-Terry over the tournament's games) come with every table.
"""
from __future__ import annotations

import itertools
import tomllib
import zlib

from aflsim.games import DEFAULT_GAME, get_game
from aflsim.match.play import run_jobs, series_jobs
from aflsim.match.rating import fit_ratings


def load_config(path: str) -> tuple[dict, str]:
    text = open(path, encoding="utf-8").read()
    return tomllib.loads(text), text


def _library_bots(game):
    """Every code bot in the library plus the zoo anchors. LLM bots are never included implicitly (they cost money)."""
    from aflsim.bots.registry import library
    g = get_game(game)
    return [b for b in library(game) if not b.startswith("llm:") and (not b.startswith("zoo:") or b[4:] in g.ANCHORS)]


def _pair_seed(seed0, x, y):
    return seed0 + (zlib.crc32(("%s|%s" % tuple(sorted((x, y)))).encode()) % 100000) * 10


def plan(cfg: dict, game=DEFAULT_GAME) -> dict:
    """The pairings, by phase: {"phase name": [(x, y), ...]}. Finals depend on results, so they are planned later."""
    fmt = cfg.get("format", "round_robin")
    from aflsim.bots.registry import canonical
    c = lambda lst: [canonical(b, game) for b in lst]
    if fmt in ("round_robin", "ladder"):
        bots = _library_bots(game) if cfg.get("bots") == "library" else c(cfg["bots"])
        return {"main": list(itertools.combinations(bots, 2))}
    if fmt == "groups":
        return {"group " + k: list(itertools.combinations(c(v), 2)) for k, v in cfg["groups"].items()}
    if fmt == "gauntlet":
        ch = canonical(cfg["challenger"], game)
        field = _library_bots(game) if cfg.get("field") == "library" else c(cfg["field"])
        return {"main": [(ch, f) for f in field if f != ch]}
    raise ValueError("unknown tournament format %r" % fmt)


def jobs_for(pairs, cfg, tid, game):
    g = get_game(game); seconds = float(cfg.get("seconds", g.DEFAULT_SECONDS)); n = int(cfg.get("seeds", 5)); seed0 = int(cfg.get("seed", 100000))
    logs = bool(cfg.get("logs", False))
    from aflsim.bots.registry import is_llm
    out = []
    for x, y in pairs:
        keep = logs or is_llm(x) or is_llm(y)
        out += series_jobs(x, y, n, _pair_seed(seed0, x, y), seconds, game=game, tournament_id=tid, save_log=keep, record="frames" if keep else "none")
    return out


def standings(rows, bots=None) -> list[dict]:
    """AFL ladder over the given games (optionally restricted to games between `bots`)."""
    t = {}
    for r in rows:
        if bots is not None and (r["bot_a"] not in bots or r["bot_b"] not in bots):
            continue
        for me, sf, sa, o in ((r["bot_a"], r["score_a"] or 0, r["score_b"] or 0, r["outcome"]), (r["bot_b"], r["score_b"] or 0, r["score_a"] or 0, 1.0 - r["outcome"])):
            s = t.setdefault(me, {"bot": me, "p": 0, "w": 0, "l": 0, "d": 0, "for": 0, "against": 0})
            s["p"] += 1; s["for"] += sf; s["against"] += sa
            s["w" if o == 1.0 else "d" if o == 0.5 else "l"] += 1
    for s in t.values():
        s["pts"] = 4 * s["w"] + 2 * s["d"]; s["pct"] = 100.0 * s["for"] / max(s["against"], 1)
    return sorted(t.values(), key=lambda s: (-s["pts"], -s["pct"]))


def run_tournament(path: str, store, parallel: int = 8, logs: bool | None = None, game: str | None = None, on_result=None, dry_run=False) -> dict:
    cfg, text = load_config(path)
    game = game or cfg.get("game", DEFAULT_GAME)
    if logs is not None:
        cfg["logs"] = logs
    name = cfg.get("name") or path.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".toml")
    tid = store.start_tournament(name, text)
    phases = plan(cfg, game)
    done = store.played_keys(tid)
    report = {"name": name, "id": tid, "phases": {}}
    for phase, pairs in phases.items():
        jobs = [j for j in jobs_for(pairs, cfg, tid, game) if (j.bot_a, j.bot_b, j.seed) not in done]
        report["phases"][phase] = {"pairs": len(pairs), "to_play": len(jobs)}
        if not dry_run and jobs:
            run_jobs(jobs, store, parallel, on_result=on_result)
    if cfg.get("format") == "groups" and cfg.get("finals"):
        rows = store.matches(tournament_id=tid)
        finalists = []
        for k, members in cfg["groups"].items():
            from aflsim.bots.registry import canonical
            mem = {canonical(b, game) for b in members}
            finalists += [s["bot"] for s in standings(rows, mem)[:int(cfg["finals"])]]
        pairs = [(x, y) for x, y in itertools.combinations(finalists, 2)]
        done = store.played_keys(tid)
        jobs = [j for j in jobs_for(pairs, cfg, tid, game) if (j.bot_a, j.bot_b, j.seed) not in done]
        report["phases"]["finals"] = {"pairs": len(pairs), "to_play": len(jobs), "finalists": finalists}
        if not dry_run and jobs:
            run_jobs(jobs, store, parallel, on_result=on_result)
    if not dry_run:
        store.finish_tournament(tid)
    return report


def tournament_tables(store, tid: int, game=DEFAULT_GAME) -> dict:
    """Standings (overall, per group, finals) and ratings for a tournament, from the store."""
    t = store.tournament_by_id(tid)
    cfg = tomllib.loads(t["config_toml"] or "")
    rows = store.matches(tournament_id=tid)
    g = get_game(game)
    out = {"tournament": t, "games": len(rows), "overall": standings(rows)}
    if cfg.get("format") == "groups":
        from aflsim.bots.registry import canonical
        out["groups"] = {k: standings(rows, {canonical(b, game) for b in v}) for k, v in cfg["groups"].items()}
    matches = [{"a": r["bot_a"], "b": r["bot_b"], "score": r["outcome"]} for r in rows]
    anchors = [a for a in ("zoo:" + z for z in g.ANCHORS) if any(m["a"] == a or m["b"] == a for m in matches)]
    out["ratings"] = fit_ratings(matches, anchors=anchors or None) if matches else {}
    return out
