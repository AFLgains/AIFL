"""Games are folders. Each game package (``aflsim.games.<name>``) provides the contract the shared machinery uses:

    NAME, ENGINE_VERSION, DEFAULT_SECONDS, ANCHORS
    Rules / make_rules(seconds)           the laws of the game (a frozen dataclass)
    Game(rules, seed)                     with observation(recent), apply_actions(team, actions),
                                          run_window(on_frame=None) -> (events, trigger), snapshot(), clone(),
                                          done, result, score, stats, team_stats, t, meta(), end(result, note)
    new_game(rules, seed, mirror=True)    a fresh game, set up fairly (mirrored player attributes)
    action_to_dict(a) / action_exact(a) / action_from_dict(d, params, exact)    orders to and from the log
    ZOO                                   the built-in bots, and zoo_hash() / source_hash(*files) for fingerprints
    special_bot(kind, arg, team, rules, seed, load)   game-specific spec kinds (random, idle, noisy:...)
    make_search(inner_spec, opts, team, rules, seed)  the `search[...]:` look-ahead wrapper
    build_llm_bot(cfg, team, rules, seed)             instruction bots from bots/<game>/llm/*.toml
    encoder()                             the value model's state encoder (encode_state, FEATURE_NAMES, N_FEATURES)
    install_compat()                      import aliases so bots written against older kits still load
    render_video(ep, out, **opts)         video of a game log (the renderer lives in the game: it draws its own ground)

The machinery never assumes a player count or a ground; everything game-specific lives in the game's package.
"""
from __future__ import annotations

import contextvars
import importlib
import os

DEFAULT_GAME = "afl8"
_ENGINE = contextvars.ContextVar("aflsim_engine", default=None)          # {game: version} for one app request
ENV = "AFLSIM_ENGINE"                                                     # "afl8=1": a whole process (and its workers)


def get_game(name: str | None = None):
    return importlib.import_module("aflsim.games.%s" % (name or DEFAULT_GAME))


# ---- engine versions. A game plays its current ENGINE_VERSION; a game that keeps an older one playable lists the
# rule changes that bring it back in OLD_ENGINES ({1: {...rules overrides}}). Selecting an engine (the CLI's --engine,
# the app's top bar) makes make_rules() build that version's laws and every result get recorded under it.
def engines(g) -> list[int]:
    """The engine versions this game can play, newest first."""
    return sorted({g.ENGINE_VERSION, *getattr(g, "OLD_ENGINES", {})}, reverse=True)


def engine_version(g) -> int:
    """The engine version in force: this request's (app), else this process's (--engine), else the game's current."""
    sel = _ENGINE.get() or {}
    if g.NAME in sel:
        return sel[g.NAME]
    for part in os.environ.get(ENV, "").split(","):
        name, _, v = part.partition("=")
        if name.strip() == g.NAME and v.strip():
            return int(v)
    return g.ENGINE_VERSION


def engine_rules(g) -> dict:
    """The rules overrides that make the engine in force (none for the current version)."""
    return dict(getattr(g, "OLD_ENGINES", {}).get(engine_version(g), {}))


def check_engine(g, version: int) -> int:
    version = int(version)
    if version not in engines(g):
        raise ValueError("%s has no engine v%d (it can play %s)" % (g.NAME, version, ", ".join("v%d" % v for v in engines(g))))
    return version


def select_engine(name: str, version: int | None):
    """For this process and the worker processes it starts (they inherit the environment)."""
    if version is None:
        return
    g = get_game(name); check_engine(g, version)
    rest = [p for p in os.environ.get(ENV, "").split(",") if p and p.partition("=")[0] != name]
    os.environ[ENV] = ",".join(rest + ["%s=%d" % (name, int(version))])


def use_engine(name: str, version: int):
    """For the current context only (an app request): returns a token for reset_engine."""
    check_engine(get_game(name), version)
    return _ENGINE.set({**(_ENGINE.get() or {}), name: int(version)})


def reset_engine(token):
    _ENGINE.reset(token)
