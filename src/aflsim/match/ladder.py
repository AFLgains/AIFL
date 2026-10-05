"""The ladder: every stored match of one game length and engine version, fitted into one rating per bot.

By default only matches played by each bot's CURRENT code count (its hash must match the library's file today), so
editing a bot starts it afresh instead of letting it inherit the old version's rating. Bots that no longer exist in
the library drop out. `current_only=False` fits every version as stored (history).
"""
from __future__ import annotations

import numpy as np

from aflsim.games import DEFAULT_GAME, get_game
from aflsim.games import engine_version as current_engine
from aflsim.match.rating import bootstrap_one, fit_one, fit_ratings


def _current_hashes(labels, game):
    from aflsim.bots.registry import bot_hash
    out = {}
    for lb in labels:
        try:
            out[lb] = bot_hash(lb, game)
        except (FileNotFoundError, KeyError, ValueError):
            out[lb] = None
    return out


def ladder_matches(store, seconds, engine_version=None, current_only=True, game=DEFAULT_GAME):
    g = get_game(game)
    ev = current_engine(g) if engine_version is None else engine_version
    rows = store.matches(seconds=seconds, engine_version=ev)
    if current_only:
        cur = _current_hashes({r["bot_a"] for r in rows} | {r["bot_b"] for r in rows}, game)
        rows = [r for r in rows if cur.get(r["bot_a"]) and cur.get(r["bot_b"]) and r["hash_a"] == cur[r["bot_a"]] and r["hash_b"] == cur[r["bot_b"]]]
    return rows


def ladder(store, seconds, engine_version=None, current_only=True, game=DEFAULT_GAME):
    """Returns (ratings {label: elo}, games {label: n}, n_matches)."""
    g = get_game(game)
    rows = ladder_matches(store, seconds, engine_version, current_only, game)
    matches = [{"a": r["bot_a"], "b": r["bot_b"], "score": r["outcome"]} for r in rows]
    anchors = ["zoo:" + z for z in g.ANCHORS]
    ratings = fit_ratings(matches, anchors=anchors)
    games = {}
    for r in rows:
        games[r["bot_a"]] = games.get(r["bot_a"], 0) + 1; games[r["bot_b"]] = games.get(r["bot_b"], 0) + 1
    return ratings, games, len(rows)


def pick_panel(ratings: dict, size: int = 16, anchors=()) -> list[str]:
    """Opponents spread evenly through the ladder by rank, plus the anchors and the current top bot."""
    ranked = sorted(ratings, key=lambda lb: -ratings[lb])
    idx = np.unique(np.linspace(0, len(ranked) - 1, min(size, len(ranked))).round().astype(int))
    panel = {ranked[i] for i in idx} | {a for a in anchors if a in ratings} | {ranked[0]}
    return sorted(panel, key=lambda lb: -ratings[lb])


def rate_bot(spec, store, seconds=None, games=10, panel_size=16, parallel=8, seed0=4_400_000, game=DEFAULT_GAME, on_result=None, boot=1000):
    """Place one bot on the ladder: play it against a spread of rated opponents (both ends, common seeds; the games
    are stored, so the bot is on the ladder afterwards), and fit its rating with theirs held fixed."""
    from aflsim.bots.registry import canonical
    from aflsim.match.play import run_jobs, series_jobs
    g = get_game(game); seconds = float(seconds or g.DEFAULT_SECONDS)
    me = canonical(spec, game)
    ratings, _games, n = ladder(store, seconds, game=game)
    ratings = {k: v for k, v in ratings.items() if k != me}
    if len(ratings) < 3:
        raise SystemExit("no ladder at %.0f s yet (%d matches): run a ladder tournament first, e.g. tournaments/ladder_240.toml" % (seconds, n))
    panel = pick_panel(ratings, panel_size, ["zoo:" + z for z in g.ANCHORS])
    jobs = []
    for i, opp in enumerate(panel):
        jobs += series_jobs(me, opp, games, seed0 + 1000 * i, seconds, game=game, save_log=False, record="none")
    rows = run_jobs(jobs, store, parallel, on_result=on_result)
    res = [(r["bot_b"], r["outcome"]) if r["bot_a"] == me else (r["bot_a"], 1.0 - r["outcome"]) for r in rows]
    rating = fit_one(res, ratings)
    lo, hi = bootstrap_one(res, ratings, boot)
    rank = 1 + sum(1 for v in ratings.values() if v > rating)
    per = {}
    for r in rows:
        opp = r["bot_b"] if r["bot_a"] == me else r["bot_a"]
        mine = r["score_a"] - r["score_b"] if r["bot_a"] == me else r["score_b"] - r["score_a"]
        o = r["outcome"] if r["bot_a"] == me else 1.0 - r["outcome"]
        per.setdefault(opp, []).append((o, mine))
    return {"bot": me, "rating": rating, "lo": lo, "hi": hi, "rank": rank, "of": len(ratings) + 1, "panel": panel, "ratings": ratings, "per_opponent": per, "games": len(rows)}


# ------------------------------------------------------------------ the adaptive ladder: just enough games
def rating_errors(matches, ratings: dict, prior: float = 2.0) -> dict:
    """The standard error (Elo) of each bot's rating, from the information in its games: a game between two bots of
    near-equal rating tells you the most (p ~ 0.5), a mismatch very little. (The usual Bradley-Terry approximation.)"""
    from aflsim.match.rating import expected
    k = np.log(10.0) / 400.0
    info = {lb: prior * 0.25 for lb in ratings}
    for m in matches:
        if m["a"] in ratings and m["b"] in ratings:
            p = expected(ratings[m["a"]], ratings[m["b"]]); w = p * (1.0 - p)
            info[m["a"]] += w; info[m["b"]] += w
    return {lb: float(1.0 / (k * np.sqrt(i))) for lb, i in info.items()}


def adaptive_ladder(store, bots=None, seconds=None, target_se: float = 40.0, seed_opponents: int = 6, max_games: int = 9000,
                    max_per_pair: int = 6, parallel: int = 8, seed0: int = 7_000_000, game=DEFAULT_GAME, log=print) -> dict:
    """A ladder with just enough games. Every bot first plays `seed_opponents` random opponents (both ends), so the
    whole library is connected; then, round by round, every bot whose rating is still uncertain (standard error over
    `target_se` Elo) plays the closest-rated opponent it hasn't met `max_per_pair` times yet, both ends (the most
    informative game there is), and everything is refitted. It stops when every bot is under the target or after
    `max_games`. Stored games of the bots' current code on this engine count too, and the run is resumable (re-run it).
    Games are played headless (no logs: results only)."""
    import json
    import zlib
    from aflsim.bots.registry import is_llm, library
    from aflsim.match.play import MatchJob, run_jobs
    g = get_game(game); seconds = float(seconds or g.DEFAULT_SECONDS); ev = current_engine(g)
    bots = sorted(bots or [b for b in library(game) if not is_llm(b)])
    cfg = {"format": "adaptive ladder", "bots": len(bots), "seconds": seconds, "target_se": target_se, "engine_version": ev}
    tid = store.start_tournament("ladder v%d %ds (adaptive)" % (ev, seconds), json.dumps(cfg))
    anchors = ["zoo:" + z for z in g.ANCHORS]
    rng = np.random.default_rng(seed0)
    played = 0

    def current():
        rows = [r for r in ladder_matches(store, seconds, ev, True, game) if r["bot_a"] in bots and r["bot_b"] in bots]
        return [{"a": r["bot_a"], "b": r["bot_b"], "score": r["outcome"]} for r in rows]

    def pair_counts(matches):
        c = {}
        for m in matches:
            key = tuple(sorted((m["a"], m["b"]))); c[key] = c.get(key, 0) + 1
        return c

    def play(pairs, counts, label):
        nonlocal played
        jobs = []
        for x, y in pairs:
            key = tuple(sorted((x, y))); n = counts.get(key, 0) // 2
            sd = seed0 + (zlib.crc32(("%s|%s" % key).encode()) % 100000) * 10 + n
            jobs += [MatchJob(x, y, sd, seconds, game=game, record="none", save_log=False, tournament_id=tid),
                     MatchJob(y, x, sd, seconds, game=game, record="none", save_log=False, tournament_id=tid)]
            counts[key] = counts.get(key, 0) + 2
        log("  %s: %d games" % (label, len(jobs)))
        run_jobs(jobs, store, parallel)
        played += len(jobs)

    # 1. connect everyone: random opponents for anyone with few games so far
    matches = current(); counts = pair_counts(matches)
    per_bot = {b: 0 for b in bots}
    for m in matches:
        per_bot[m["a"]] += 1; per_bot[m["b"]] += 1
    seed_pairs = set()
    for b in bots:
        need = seed_opponents - per_bot[b] // 2
        others = [o for o in bots if o != b]
        for o in rng.permutation(others)[:max(0, need)]:
            seed_pairs.add(tuple(sorted((b, str(o)))))
    if seed_pairs:
        log("ladder: %d bots; seed round so every bot meets %d opponents" % (len(bots), seed_opponents))
        play(sorted(seed_pairs), counts, "seed round")
    # 2. top up the uncertain ones against their closest-rated opponents
    rnd = 0; history = {b: [] for b in bots}; stalled = set()
    while True:
        matches = current(); counts = pair_counts(matches)
        ratings = fit_ratings(matches, labels=bots, anchors=anchors); se = rating_errors(matches, ratings)
        for b in bots:                                                       # more games aren't helping a bot (e.g. one that loses
            history[b].append(se[b])                                         # every game: mismatches carry almost no information)
            if len(history[b]) > 8 and history[b][-9] - se[b] < 1.0 and se[b] > target_se:
                stalled.add(b)
        wide = sorted([b for b in bots if se[b] > target_se and b not in stalled], key=lambda b: -se[b])
        log("ladder round %d: %d games in total, %d bots still over +-%.0f Elo (widest: %s +-%.0f)%s"
            % (rnd, len(matches), len(wide), target_se, wide[0] if wide else "-", se[wide[0]] if wide else 0,
               "; given up on %d that more games aren't helping (%s)" % (len(stalled), ", ".join(sorted(stalled))) if stalled else ""))
        if not wide or played >= max_games:
            break
        pairs, used = [], {}
        for b in wide:
            if used.get(b, 0) >= 2:
                continue
            opp = sorted((o for o in bots if o != b and counts.get(tuple(sorted((b, o))), 0) < 2 * max_per_pair and used.get(o, 0) < 3),
                         key=lambda o: abs(ratings[o] - ratings[b]))
            if not opp:
                continue
            o = opp[0]; pairs.append((b, o)); used[b] = used.get(b, 0) + 1; used[o] = used.get(o, 0) + 1
        if not pairs:
            log("ladder: no more useful pairings (every close pair has met %d times)" % max_per_pair); break
        rnd += 1
        play(pairs, counts, "round %d" % rnd)
    matches = current()
    ratings = fit_ratings(matches, labels=bots, anchors=anchors); se = rating_errors(matches, ratings)
    games = {b: 0 for b in bots}
    for m in matches:
        games[m["a"]] += 1; games[m["b"]] += 1
    snap = store.save_ratings("ladder", seconds, ev, len(matches), ratings)
    store.finish_tournament(tid)
    log("\nladder (engine v%d, %.0f s): %d bots, %d games (%d played now); ratings snapshot %d" % (ev, seconds, len(bots), len(matches), played, snap))
    log("  %4s %-40s %7s %8s %6s" % ("rank", "bot", "Elo", "+- 95%", "games"))
    for i, b in enumerate(sorted(bots, key=lambda b: -ratings[b]), 1):
        log("  %4d %-40s %7.0f %8.0f %6d" % (i, b, ratings[b], 1.96 * se[b], games[b]))
    return {"ratings": ratings, "se": se, "games": games, "n": len(matches), "played": played, "tournament_id": tid}
