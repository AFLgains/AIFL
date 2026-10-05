"""Video of any stored match.

    render_match(42)                                  # -> videos/afl8/42.mp4
    render_match(42, value_bar=True, t0=60, t1=90)    # -> videos/afl8/42_valuebar_60-90.mp4

Where the game comes from:
  * a stored log (always kept for single matches and LLM games);
  * otherwise, a re-simulation: code bots are deterministic given (spec, hash, seed, length, engine version), so the
    game is played again and checked against the stored score before anything is rendered. A bot whose code has
    changed since (different hash) cannot be re-simulated and is refused.

The value bar needs full game states, which a log does not keep. They are rebuilt by replaying BOTH teams' recorded
orders from the same seed (the engine is deterministic given the orders), which works for any game, LLM games
included; the rebuilt game must reach the stored score, or nothing is drawn.
"""
from __future__ import annotations

import os

from aflsim import paths
from aflsim.bots.base import TeamController
from aflsim.games import DEFAULT_GAME, engines, get_game


class ReplayOrders(TeamController):
    """Hands back one team's recorded orders, decision by decision."""

    def __init__(self, team, decisions, game_mod):
        super().__init__(team); self.recorded = [d["teams"][team] for d in decisions]; self.k = 0; self.g = game_mod; self.name = "replay"

    def choose_actions(self, state, problems):
        rec = self.recorded[self.k] if self.k < len(self.recorded) else {"actions": [], "intent": ""}
        params = (rec.get("detail") or {}).get("params") or {}
        exact = rec.get("exact") or [None] * len(rec["actions"])
        self.k += 1
        return rec.get("intent", ""), [self.g.action_from_dict(d, params, x) for d, x in zip(rec["actions"], exact)]


def _rules_of(ep, g):
    return g.Rules.from_log(ep["meta"]["rules"])


def value_series(ep, model="value_pos", game=DEFAULT_GAME):
    """[[game time, P(team A scores next)], ...] for a logged game, by replaying its orders."""
    from aflsim.engine import run_match
    from aflsim.value.function import ValueFunction
    g = get_game(game); vf = ValueFunction(model, game)
    rules = _rules_of(ep, g); series = []
    new = run_match(g, ReplayOrders("A", ep["decisions"], g), ReplayOrders("B", ep["decisions"], g), rules, ep["meta"]["seed"],
                    record="none", on_state=lambda game_obj, state: series.append([round(float(state["time"]), 2), vf.of_state(state)]))
    old = (ep["stats"]["score_A"], ep["stats"]["score_B"]); now = (new["stats"]["score_A"], new["stats"]["score_B"])
    if old != now or len(new["decisions"]) != len(ep["decisions"]):
        raise RuntimeError("replaying the recorded orders diverged (%d-%d v %d-%d): no value bar" % (old + now))
    return series


def resimulate(row: dict, game=DEFAULT_GAME) -> dict:
    """Play a stored code-bot match again, exactly, and check it against the store."""
    from aflsim.bots.registry import bot_hash, is_llm, load_bot
    from aflsim.engine import run_match
    for side in ("a", "b"):
        spec = row["bot_" + side]
        if is_llm(spec):
            raise RuntimeError("match %s has an LLM bot and no stored log: it cannot be replayed" % row["id"])
        if bot_hash(spec, game) != row["hash_" + side]:
            raise RuntimeError("%s has changed since match %s was played (hash %s, now %s): cannot re-simulate" % (spec, row["id"], row["hash_" + side], bot_hash(spec, game)))
    if row["seed"] is None:
        raise RuntimeError("match %s has no seed (a legacy ladder row): nothing to replay" % row["id"])
    g = get_game(game)
    if row["engine_version"] not in engines(g):
        raise RuntimeError("match %s was played on engine v%s, which this code can no longer play" % (row["id"], row["engine_version"]))
    rules = g.make_rules(row["seconds"], **getattr(g, "OLD_ENGINES", {}).get(row["engine_version"], {}))
    a = load_bot(row["bot_a"], "A", rules, row["seed"], game); b = load_bot(row["bot_b"], "B", rules, row["seed"] + 1000, game)
    ep = run_match(g, a, b, rules, row["seed"], row["max_decisions"])
    if (ep["stats"]["score_A"], ep["stats"]["score_B"]) != (row["score_a"], row["score_b"]):
        raise RuntimeError("re-simulation of match %s diverged: %d-%d, stored %d-%d" % (row["id"], ep["stats"]["score_A"], ep["stats"]["score_B"], row["score_a"], row["score_b"]))
    ep["meta"]["packs"] = {"A": {"name": row["bot_a"], "motto": "", "scripted": True}, "B": {"name": row["bot_b"], "motto": "", "scripted": True}}
    return ep


def game_log(row: dict, game=DEFAULT_GAME) -> dict:
    from aflsim.engine import load_log
    if row.get("log_path") and os.path.exists(row["log_path"]):
        return load_log(row["log_path"])
    return resimulate(row, game)


def clip(ep, t0=None, t1=None):
    if t0 is None and t1 is None:
        return ep
    t0 = t0 or 0.0; t1 = t1 if t1 is not None else 1e9
    out = dict(ep)
    out["frames"] = [f for f in ep["frames"] if t0 - 1e-6 <= f["t"] <= t1 + 1e-6]
    out["events"] = [e for e in ep["events"] if t0 - 5.0 <= e["t"] <= t1 + 1e-6]           # a little history so the possession chain reads right
    out["score_start"] = score_before(ep, t0 - 5.0)
    return out


def score_before(ep, t):
    """Goals and behinds per team from score events strictly before time t (the scoreboard a clip opens on)."""
    tally = {"A": [0, 0], "B": [0, 0]}
    for e in ep["events"]:
        if e["type"] == "score" and e["t"] < t:
            tally[e["team"]][0 if e.get("kind") == "goal" else 1] += 1
    return tally


def short_name(spec: str) -> str:
    """A readable team name for the scoreboard: 'mine/my_bot' -> 'my_bot', 'search:...my_bot' -> 'my_bot+search'."""
    if spec.startswith("search"):
        return short_name(spec.split(":", 1)[1].split("]:")[-1]) + "+search"
    return spec.rstrip("/").split("/")[-1].replace("zoo:", "")


def render_match(match_id: int, store=None, out=None, speed=2.0, value_bar=False, model="value_pos", energy=False, t0=None, t1=None,
                 view=60.0, style="retro", name_a=None, name_b=None, game=DEFAULT_GAME, preview_t=None) -> str:
    from aflsim.match.store import Store
    st = store or Store(game)
    row = st.match(int(match_id))
    if row is None:
        raise SystemExit("no match %s in %s" % (match_id, st.path))
    ep = game_log(row, game)
    values = value_series(ep, model, game) if value_bar else None
    suffix = ("_valuebar" if value_bar else "") + ("_%g-%g" % (t0 or 0, t1 if t1 is not None else row["seconds"]) if (t0 is not None or t1 is not None) else "")
    out = out or os.path.join(paths.videos_dir(game), "%d%s.%s" % (row["id"], suffix, "png" if preview_t is not None else "mp4"))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    g = get_game(game)
    g.render_video(clip(ep, t0, t1), out, speed=speed, name_a=name_a or short_name(row["bot_a"]), name_b=name_b or short_name(row["bot_b"]),
             values=values, team_energy=energy, view=view, style=style, preview_t=preview_t)
    return out
