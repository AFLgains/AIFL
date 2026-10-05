"""Run one match between two controllers and record it: decisions, intents, orders, events, statistics and (unless
headless) a dense trajectory for replay. Game-agnostic: it only uses the game contract (see the games package).

`decide_and_advance` is the same single step, exposed for rollouts (look-ahead, data generation, what-if), so every
simulation in the repo steps the game the same way.
"""
from __future__ import annotations

import time


def _engine_of(game_mod, rules) -> int:
    """The engine version these rules are the laws of (a game that keeps old engines playable says which)."""
    f = getattr(game_mod, "recorded_engine", None)
    return f(rules) if f else game_mod.ENGINE_VERSION


def decide_and_advance(game, ctls: dict, problems: dict, recent: list, on_frame=None):
    """Both controllers see the state, their orders are applied, then one physics window runs.
    Returns (events in the window, trigger for the next decision)."""
    state = game.observation(recent)
    for team, ctl in ctls.items():
        try:
            _intent, actions = ctl.choose_actions(state, problems[team])
        except Exception:                                                  # noqa: BLE001  (rollouts must not die on a bot bug)
            actions = []
        problems[team] = getattr(ctl, "last_problems", [])
        game.apply_actions(team, actions)
    return game.run_window(on_frame)


def run_match(game_mod, ctl_a, ctl_b, rules, seed: int = 0, max_decisions: int | None = None, setup=None,
              token_budget: int | None = None, on_state=None, record: str = "frames", verbose=False, mirror=True) -> dict:
    """Play a match to completion and return its log (the dict that logs.save_log writes).

    setup(game): called before the first decision (scripted scenarios); by default the game's fair setup is used.
    on_state(game, state): read-only hook at every decision point, before the controllers see the state.
    record: "frames" keeps the replay trajectory; "none" is headless (tournaments, evolution, RL: much smaller logs).
    """
    game = game_mod.new_game(rules, seed, mirror=mirror) if setup is None else game_mod.Game(rules, seed)
    if setup is not None:
        setup(game)
    frames = [game.snapshot()] if record == "frames" else []
    on_frame = frames.append if record == "frames" else None
    decisions = []
    problems = {"A": [], "B": []}
    recent = []
    t_wall = time.time()
    n_dec = 0
    tokens_used = 0
    trigger = "start"
    ctls = {"A": ctl_a, "B": ctl_b}
    while not game.done:
        state = game.observation(recent)
        state["decision_reason"] = trigger
        if on_state is not None:
            on_state(game, state)
        for ctl in ctls.values():                                          # a searching controller clones the true game
            hook = getattr(ctl, "observe_game", None) or getattr(getattr(ctl, "inner", None), "observe_game", None)
            if hook is not None:
                hook(game)
        entry = {"t": game.t, "trigger": trigger, "teams": {}}
        chosen = {team: ctl.choose_actions(state, problems[team]) for team, ctl in ctls.items()}
        for team, ctl in ctls.items():
            intent, actions = chosen[team]
            problems[team] = getattr(ctl, "last_problems", [])
            game.apply_actions(team, actions)
            entry["teams"][team] = {"controller": ctl.name, "prediction": getattr(ctl, "last_prediction", ""), "intent": intent,
                                    "actions": [game_mod.action_to_dict(a) for a in actions], "problems": list(problems[team]),
                                    "llm": dict(getattr(ctl, "last_info", {}) or {}), "detail": getattr(ctl, "last_detail", None),
                                    "exact": [game_mod.action_exact(a) for a in actions]}   # unrounded, so a replay of the orders is exact
        if verbose:
            print("t=%5.1f [%s]  A: %s | B: %s" % (game.t, trigger[:10], entry["teams"]["A"]["intent"][:70], entry["teams"]["B"]["intent"][:70]), flush=True)
        recent, trigger = game.run_window(on_frame)
        entry["events"] = recent
        decisions.append(entry)
        n_dec += 1
        tokens_used += sum((entry["teams"][t]["llm"].get("prompt_tokens") or 0) + (entry["teams"][t]["llm"].get("completion_tokens") or 0) for t in entry["teams"])
        if max_decisions and n_dec >= max_decisions:
            game.end("stopped")
        if token_budget and tokens_used >= token_budget and not game.done:
            game.end("token budget", note="%d tokens used" % tokens_used)
    stats = dict(game.stats)
    stats.update({"result": game.result, "score_A": game.score["A"], "score_B": game.score["B"], "margin": game.score["A"] - game.score["B"],
                  "team_stats": game.team_stats, "duration_s": round(game.t, 2), "decisions": n_dec, "tokens_used": tokens_used, "wall_s": round(time.time() - t_wall, 1),
                  "llm_errors": {"A": getattr(ctl_a, "errors", []), "B": getattr(ctl_b, "errors", [])}})
    meta = {"game": game_mod.NAME, "engine_version": _engine_of(game_mod, rules), "seed": seed, "rules": dict(rules.__dict__),
            "team_A": ctl_a.name, "team_B": ctl_b.name}
    meta.update(game.meta())
    return {"meta": meta, "stats": stats, "decisions": decisions, "events": game.events, "frames": frames}
