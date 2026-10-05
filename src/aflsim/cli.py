"""afl: the one entry point.  python afl.py <command> --help  for any command's options.

  PLAY       match, tournament, tournament-status
  RATINGS    rate, ladder, h2h, import-legacy
  RESULTS    results, show, export
  VIDEO      render
  BOTS       bots, check, add, botkit
  APP        app   (the web front end)
"""
from __future__ import annotations

import argparse
import os
import sys

from aflsim.games import DEFAULT_GAME, engine_version, select_engine


def _store(a):
    from aflsim.match.store import Store
    return Store(a.game)


def _seconds(a):
    from aflsim.games import get_game
    return float(a.seconds or get_game(a.game).DEFAULT_SECONDS)


def _fmt_row(r):
    return "#%-6s %-38s %3s - %-3s %-38s seed %-8s %4.0fs  %s" % (r["id"], r["bot_a"][-38:], r["score_a"] if r["score_a"] is not None else "?",
                                                               r["score_b"] if r["score_b"] is not None else "?", r["bot_b"][-38:], r["seed"], r["seconds"], r["created"][:16])


# ------------------------------------------------------------------ play
def cmd_match(a):
    from aflsim.match.play import record, run_job, series_jobs
    from aflsim.match.rating import score_summary
    st = _store(a); seconds = _seconds(a)
    jobs = series_jobs(a.bot_a, a.bot_b, a.games, a.seed, seconds, both_ends=a.both_ends, game=a.game, max_decisions=a.max_decisions,
                       save_log=not a.no_log, record="none" if a.no_log else "frames")
    rows = []
    if a.games * (2 if a.both_ends else 1) > 1 and a.parallel > 1:
        from aflsim.match.play import run_jobs
        rows = run_jobs(jobs, st, a.parallel, on_result=lambda r: print(_fmt_row(r), flush=True))
    else:
        for j in jobs:
            r = record(st, run_job(j)); rows.append(r); print(_fmt_row(r), flush=True)
            if r["first_errors"]["A"] or r["first_errors"]["B"]:
                print("   bot errors:", r["first_errors"])
    if len(rows) > 1:
        from aflsim.bots.registry import canonical
        me = canonical(a.bot_a, a.game)
        s = score_summary([r["outcome"] if r["bot_a"] == me else 1.0 - r["outcome"] for r in rows])
        margin = sum((r["score_a"] - r["score_b"]) * (1 if r["bot_a"] == me else -1) for r in rows) / len(rows)
        print("\n%s v %s: %d-%d-%d (W-L-D), score %.3f +/- %.3f, mean margin %+.1f, Elo gap %+.0f (%+.0f to %+.0f)"
              % (me, canonical(a.bot_b, a.game), s["w"], s["l"], s["d"], s["score"], 2 * s["se"], margin, s["elo"], s["elo_lo"], s["elo_hi"]))
    if a.video or a.value_bar:
        from aflsim.video.render import render_match
        for r in rows[:1] if len(rows) > 1 else rows:
            out = render_match(r["id"], st, speed=a.speed, value_bar=a.value_bar, game=a.game)
            print("video:", out)


def cmd_tournament(a):
    from aflsim.match.tournament import run_tournament, tournament_tables
    st = _store(a)
    rep = run_tournament(a.config, st, a.parallel, logs=True if a.logs else None, game=a.game, dry_run=a.dry_run,
                         on_result=(lambda r: print(_fmt_row(r), flush=True)) if a.verbose else None)
    for ph, info in rep["phases"].items():
        print("%-12s %s" % (ph, info))
    if not a.dry_run:
        _print_tables(tournament_tables(st, rep["id"], a.game))


def _print_tables(t):
    def table(rows, title):
        print("\n%s" % title)
        print("  %-3s %-40s %3s %3s %3s %3s %5s %7s" % ("#", "bot", "P", "W", "L", "D", "Pts", "%"))
        for i, s in enumerate(rows, 1):
            print("  %-3d %-40s %3d %3d %3d %3d %5d %7.1f" % (i, s["bot"][-40:], s["p"], s["w"], s["l"], s["d"], s["pts"], s["pct"]))
    print("\n%s (id %d): %d games, status %s" % (t["tournament"]["name"], t["tournament"]["id"], t["games"], t["tournament"]["status"]))
    for k, rows in (t.get("groups") or {}).items():
        table(rows, "group " + k)
    table(t["overall"], "overall")
    if t["ratings"]:
        print("\n  ratings (Bradley-Terry over this tournament's games):")
        for lb, r in sorted(t["ratings"].items(), key=lambda kv: -kv[1]):
            print("    %-42s %6.0f" % (lb[-42:], r))


def cmd_tournament_status(a):
    from aflsim.match.tournament import tournament_tables
    st = _store(a)
    ts = st.tournaments()
    if not a.id:
        for t in ts:
            print("%3d  %-30s %-9s started %s  %d games" % (t["id"], t["name"], t["status"], t["created"][:16], len(st.matches(tournament_id=t["id"]))))
        return
    t = st.tournament(a.id) or (st.tournament_by_id(int(a.id)) if a.id.isdigit() else None)
    if not t:
        raise SystemExit("no tournament %s" % a.id)
    _print_tables(tournament_tables(st, t["id"], a.game))


# ------------------------------------------------------------------ ratings
def cmd_rate(a):
    from aflsim.match.ladder import rate_bot
    st = _store(a)
    r = rate_bot(a.bot, st, _seconds(a), a.games, a.panel, a.parallel, game=a.game)
    print("\n  %-36s %6s  %-12s %s" % ("opponent", "rating", "W-L-D", "mean margin"))
    for opp in r["panel"]:
        rr = r["per_opponent"].get(opp, [])
        w = sum(1 for o, _ in rr if o == 1); l = sum(1 for o, _ in rr if o == 0)
        print("  %-36s %6.0f  %3d-%3d-%-3d %+6.1f" % (opp[-36:], r["ratings"][opp], w, l, len(rr) - w - l, sum(m for _, m in rr) / max(len(rr), 1)))
    print("\n  %s: RATING %.0f (95%% interval %.0f to %.0f), rank %d of %d  (%d games, stored)" % (r["bot"], r["rating"], r["lo"], r["hi"], r["rank"], r["of"], r["games"]))


def cmd_newladder(a):
    from aflsim.match.ladder import adaptive_ladder
    adaptive_ladder(_store(a), seconds=_seconds(a), target_se=a.target, seed_opponents=a.seed_opponents, max_games=a.max_games,
                    parallel=a.parallel, game=a.game)


def cmd_ladder(a):
    from aflsim.match.ladder import ladder
    st = _store(a)
    ratings, games, n = ladder(st, _seconds(a), current_only=not a.history, game=a.game)
    if not ratings:
        print("no games at %.0f s yet. Play a ladder tournament (tournaments/ladder_240.toml) or `afl import-legacy` for the old 120 s ladder." % _seconds(a)); return
    ranked = sorted(ratings.items(), key=lambda kv: -kv[1])
    print("ladder at %.0f s: %d bots, %d games (anchors %s = 1500 on average)" % (_seconds(a), len(ratings), n, "zone/ontario/rules/runner/keeper"))
    for i, (lb, r) in enumerate(ranked[:a.top] if a.top else ranked, 1):
        print("  %3d  %-44s %6.0f  (%d games)" % (i, lb[-44:], r, games.get(lb, 0)))
    if a.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from aflsim import paths
        rows = ranked[:a.top] if a.top else ranked
        fig, ax = plt.subplots(figsize=(9, max(4, 0.22 * len(rows))))
        ax.barh([lb for lb, _ in rows][::-1], [r for _, r in rows][::-1], color="#2e7d32"); ax.axvline(1500, color="grey", ls=":")
        ax.set_xlabel("rating (anchors = 1500)"); ax.set_title("ladder, %.0f-second games" % _seconds(a)); fig.tight_layout()
        out = os.path.join(paths.home(), "results", "ladder_%ds.png" % int(_seconds(a))); fig.savefig(out, dpi=110); print(out)
    if a.snapshot:
        from aflsim.games import get_game
        print("snapshot id", st.save_ratings("ladder", _seconds(a), engine_version(get_game(a.game)), n, ratings))


def cmd_h2h(a):
    from aflsim.bots.registry import canonical
    from aflsim.match.rating import score_summary
    st = _store(a); x = canonical(a.bot_a, a.game); y = canonical(a.bot_b, a.game)
    rows = [r for r in st.matches(bot=x) if {r["bot_a"], r["bot_b"]} == {x, y} and (a.seconds is None or abs(r["seconds"] - float(a.seconds)) < 1e-6)]
    if not rows:
        print("no stored games between %s and %s" % (x, y)); return
    s = score_summary([r["outcome"] if r["bot_a"] == x else 1.0 - r["outcome"] for r in rows])
    scored = [r for r in rows if r["score_a"] is not None]
    margin = sum((r["score_a"] - r["score_b"]) * (1 if r["bot_a"] == x else -1) for r in scored) / max(len(scored), 1)
    print("%s v %s: %d games, %d-%d-%d, score %.3f +/- %.3f, mean margin %+.1f, Elo gap %+.0f (%+.0f to %+.0f)"
          % (x, y, s["n"], s["w"], s["l"], s["d"], s["score"], 2 * s["se"], margin, s["elo"], s["elo_lo"], s["elo_hi"]))


def cmd_import_legacy(a):
    from aflsim.match.legacy import import_progress
    print(import_progress(a.path, _store(a), a.seconds or 120.0, a.game))


# ------------------------------------------------------------------ results
def cmd_results(a):
    st = _store(a)
    from aflsim.bots.registry import canonical
    rows = st.matches(bot=canonical(a.bot, a.game) if a.bot else None, tournament_id=a.tournament, since=a.since, limit=a.limit, newest_first=True)
    rows = [r for r in rows if r["source"] != "legacy"] if not a.legacy else rows
    for r in rows[::-1]:
        print(_fmt_row(r))
    print("(%d shown; %d matches in %s)" % (len(rows), st.count(), st.path))


def cmd_show(a):
    import json
    st = _store(a); r = st.match(a.id)
    if not r:
        raise SystemExit("no match %s" % a.id)
    stats = json.loads(r["stats_json"] or "{}")
    print(_fmt_row(r))
    print("  engine v%s, result %s, %s decisions, %s tokens, %.1f s wall" % (r["engine_version"], r["result"], r["decisions"], r["tokens"], r["wall_s"] or 0))
    print("  hashes: A %s  B %s   errors: A %s  B %s" % (r["hash_a"], r["hash_b"], r["errors_a"], r["errors_b"]))
    print("  log: %s" % (r["log_path"] or "(none: code-bot games are re-simulated for video)"))
    ts = stats.get("team_stats") or {}
    if ts:
        keys = sorted(set(ts.get("A", {})) | set(ts.get("B", {})))
        print("  %-14s %6s %6s" % ("", "A", "B"))
        for k in keys:
            print("  %-14s %6s %6s" % (k, ts.get("A", {}).get(k, ""), ts.get("B", {}).get(k, "")))


def cmd_export(a):
    import csv
    st = _store(a); rows = st.matches()
    cols = ["id", "created", "seconds", "seed", "bot_a", "bot_b", "score_a", "score_b", "outcome", "result", "tournament_id", "source", "hash_a", "hash_b", "engine_version"]
    out = a.csv or os.path.join(os.path.dirname(st.path), "%s_matches.csv" % a.game)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])
    print("%d matches -> %s" % (len(rows), out))


# ------------------------------------------------------------------ video
def cmd_render(a):
    from aflsim.video.render import render_match
    print(render_match(a.id, _store(a), a.out, a.speed, a.value_bar, a.model, a.energy, a.t0, a.t1, a.view, a.style, game=a.game, preview_t=a.preview))


# ------------------------------------------------------------------ bots
def cmd_bots(a):
    from aflsim.bots.registry import library
    from aflsim.match.ladder import ladder
    ratings = {}
    try:
        ratings, _g, _n = ladder(_store(a), _seconds(a), game=a.game)
    except Exception:                                                      # noqa: BLE001  (an empty store is fine)
        pass
    for b in library(a.game):
        r = ratings.get(b)
        print("  %-46s %s" % (b, "%6.0f" % r if r is not None else "     -"))


def cmd_check(a):
    from aflsim.bots.check import check_bot
    rep = check_bot(a.bot, a.game, seconds=a.seconds or 30.0)
    for line in rep["lines"]:
        print(line)
    if not rep["ok"]:
        sys.exit(1)


def cmd_add(a):
    import shutil
    from aflsim import paths
    from aflsim.bots.check import check_bot
    dest = os.path.join(paths.bots_dir(a.game), "code", *a.as_.split("/")) + ".py"
    if os.path.exists(dest) and not a.force:
        raise SystemExit("%s exists (use --force to replace it)" % dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True); shutil.copyfile(a.file, dest)
    rep = check_bot(a.as_, a.game)
    for line in rep["lines"]:
        print(line)
    print("added as %s -> %s" % (a.as_, dest) if rep["ok"] else "added, but the check FAILED: fix the bot before rating it")


def cmd_botkit(a):
    from aflsim.bots.botkit import build, build_spec
    print(build(a.out, a.game) if a.full else build_spec(a.out, a.game))


# ------------------------------------------------------------------ app
def cmd_app(a):
    try:
        from aflsim.app.server import main as serve
    except ImportError as e:
        raise SystemExit("the app needs fastapi and uvicorn: pip install fastapi uvicorn  (%s)" % e)
    serve(port=a.port, open_browser=not a.no_browser)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="afl", description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--game", default=DEFAULT_GAME, help="which game (default afl8)")
    ap.add_argument("--engine", type=int, help="play (and record) an older engine version the game keeps, e.g. afl8's v1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def P(name, fn, help_):
        p = sub.add_parser(name, help=help_, description=help_); p.set_defaults(fn=fn); return p

    p = P("match", cmd_match, "play a match (or a short series) between two bots; stored, with its log")
    p.add_argument("bot_a"); p.add_argument("bot_b")
    p.add_argument("--seconds", type=float); p.add_argument("--seed", type=int, default=1); p.add_argument("--games", type=int, default=1)
    p.add_argument("--both-ends", action="store_true", help="also play every seed with the bots swapped (the fair comparison)")
    p.add_argument("--max-decisions", type=int); p.add_argument("--parallel", type=int, default=8)
    p.add_argument("--video", action="store_true"); p.add_argument("--value-bar", action="store_true"); p.add_argument("--speed", type=float, default=2.0)
    p.add_argument("--no-log", action="store_true", help="headless: don't keep the full log (code-bot games can still be re-simulated for video)")

    p = P("tournament", cmd_tournament, "run (or resume) a tournament from a TOML config")
    p.add_argument("config"); p.add_argument("--parallel", type=int, default=8); p.add_argument("--logs", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="show how many games would be played"); p.add_argument("-v", "--verbose", action="store_true")

    p = P("tournament-status", cmd_tournament_status, "list tournaments, or show one's standings")
    p.add_argument("id", nargs="?")

    p = P("rate", cmd_rate, "place one bot on the ladder (games are stored)")
    p.add_argument("bot"); p.add_argument("--seconds", type=float); p.add_argument("--games", type=int, default=10, help="seeds per opponent (x2 ends)")
    p.add_argument("--panel", type=int, default=16); p.add_argument("--parallel", type=int, default=8)

    p = P("newladder", cmd_newladder, "build the ladder for this engine with just enough games: every code bot (no LLM bots), adaptively")
    p.add_argument("--seconds", type=float); p.add_argument("--target", type=float, default=40.0, help="stop when every bot's rating is within +- this (Elo, 1 standard error)")
    p.add_argument("--seed-opponents", type=int, default=6); p.add_argument("--max-games", type=int, default=9000); p.add_argument("--parallel", type=int, default=8)

    p = P("ladder", cmd_ladder, "the rating ladder from every stored game of one length")
    p.add_argument("--seconds", type=float); p.add_argument("--top", type=int); p.add_argument("--plot", action="store_true")
    p.add_argument("--history", action="store_true", help="count every stored version of each bot, not just its current code")
    p.add_argument("--snapshot", action="store_true", help="save this ladder in the store's ratings table")

    p = P("h2h", cmd_h2h, "head-to-head record of two bots from stored games")
    p.add_argument("bot_a"); p.add_argument("bot_b"); p.add_argument("--seconds", type=float)

    p = P("import-legacy", cmd_import_legacy, "import the old repo's ladder (arena/progress.json) once")
    p.add_argument("path"); p.add_argument("--seconds", type=float, default=120.0)

    p = P("results", cmd_results, "recent matches")
    p.add_argument("--bot"); p.add_argument("--tournament", type=int); p.add_argument("--since"); p.add_argument("--limit", type=int, default=30)
    p.add_argument("--legacy", action="store_true", help="include imported legacy rows")

    p = P("show", cmd_show, "one match in detail"); p.add_argument("id", type=int)
    p = P("export", cmd_export, "all matches to CSV"); p.add_argument("--csv")

    p = P("render", cmd_render, "video of a stored match (videos/<game>/<id>.mp4)")
    p.add_argument("id", type=int); p.add_argument("--out"); p.add_argument("--speed", type=float, default=2.0)
    p.add_argument("--value-bar", action="store_true"); p.add_argument("--model", default="value_pos"); p.add_argument("--energy", action="store_true")
    p.add_argument("--from", dest="t0", type=float); p.add_argument("--to", dest="t1", type=float); p.add_argument("--view", type=float, default=60.0)
    p.add_argument("--style", default="retro", choices=["retro", "flat", "classic"]); p.add_argument("--preview", type=float, help="one frame at this time, as a PNG")

    p = P("bots", cmd_bots, "the bot library, with ladder ratings"); p.add_argument("--seconds", type=float)
    p = P("check", cmd_check, "smoke-test a bot: loads, valid orders, finishes a short game without errors")
    p.add_argument("bot"); p.add_argument("--seconds", type=float)
    p = P("add", cmd_add, "copy a bot file into the library and check it")
    p.add_argument("file"); p.add_argument("--as", dest="as_", required=True, help="library spec, e.g. mine/my_bot"); p.add_argument("--force", action="store_true")
    p = P("botkit", cmd_botkit, "build the zip for outside bot writers: the tournament kit (no engine, no league code); --full adds the engine")
    p.add_argument("--out"); p.add_argument("--full", action="store_true", help="the full kit, with the match engine (writers can play games locally)")

    p = P("app", cmd_app, "the web front end on http://127.0.0.1:8765")
    p.add_argument("--port", type=int, default=8765); p.add_argument("--no-browser", action="store_true")

    try:                                                                    # the private parts' commands, when this copy has them
        import importlib
        lab_cli = importlib.import_module("aflsim.lab_cli")
    except ModuleNotFoundError as e:
        if not (e.name or "").startswith("aflsim"):
            raise
    else:
        lab_cli.register(P)

    a = ap.parse_args(argv)
    try:
        select_engine(a.game, a.engine)
    except ValueError as e:
        raise SystemExit(str(e))
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
