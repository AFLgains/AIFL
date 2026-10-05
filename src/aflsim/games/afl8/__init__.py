"""afl8: the 8-a-side Australian Rules game on a 140 x 100 m oval. This module is the game contract that the shared
machinery (matches, tournaments, ratings, video, analyst, RL) talks to; see aflsim.games for the list.

ENGINE_VERSION is bumped by hand whenever rules or physics change behaviour. Results and ratings never mix versions.
The golden test (tests/test_golden.py) must still pass for any change that is NOT meant to change play.
"""
from __future__ import annotations

import hashlib
import os

from .actions import Action, action_to_dict, parse_actions                 # noqa: F401
from . import config
from .config import Rules
from .engine import Game

NAME = "afl8"
ENGINE_VERSION = 2          # 2: players run freely around a set play's protected area (v1 froze anyone who touched it)
DEFAULT_SECONDS = 240.0
ANCHORS = ("zone", "ontario", "rules", "runner", "keeper")                 # rating anchors, pinned to average 1500
HERE = os.path.dirname(os.path.abspath(__file__))


OLD_ENGINES = {1: config.LEGACY}                                         # v1 is still playable: its laws are LEGACY


def recorded_engine(rules) -> int:
    """The engine version a game under these rules counts as: the old version whose laws they are, else the current."""
    for v, over in sorted(OLD_ENGINES.items()):
        if all(getattr(rules, k) == val for k, val in over.items()):
            return v
    return ENGINE_VERSION


def make_rules(seconds: float | None = None, **overrides) -> Rules:
    """The laws of the engine version in force (see aflsim.games.engine_version): the current one unless an older one
    was selected. Explicit overrides win."""
    from aflsim.games import engine_rules
    import sys
    return Rules(episode_seconds=float(seconds or DEFAULT_SECONDS), **{**engine_rules(sys.modules[__name__]), **overrides})


def action_exact(a: Action):
    """The parts of an order that action_to_dict rounds for readability, at full precision (for exact replays)."""
    return [None if a.target is None else [float(a.target[0]), float(a.target[1])], float(a.power)]


def action_from_dict(d: dict, params: dict | None = None, exact=None) -> Action:
    """Rebuild an order from its logged form (replaying a stored game). `exact` (from action_exact) restores the
    unrounded target and power. A MOVE's pace comes from the log, or a Jev speed answer in the decision detail."""
    target, power = (exact[0], exact[1]) if exact is not None else (d.get("target"), float(d.get("power", 1.0)))
    act = Action(d["player"], d["action"], target=target, target_player=d.get("target_player"), opponent=d.get("opponent"), power=power)
    if d["action"] == "MOVE":
        sp = (params or {}).get("%s_speed" % d["player"])
        act.pace = d.get("pace") or (sp or {}).get("choice") or "run"
    return act


def mirror_attributes(game):
    """Fair setup: team B's player k gets exactly team A's player k's attributes, so neither side has better players."""
    for i in range(game.r.n_per_team):
        game.players["B%d" % (i + 1)].attrs = dict(game.players["A%d" % (i + 1)].attrs)


def new_game(rules: Rules, seed: int, mirror: bool = True) -> Game:
    g = Game(rules, seed)
    if mirror:
        mirror_attributes(g)
    return g


def _zoo():
    from .controllers.rules_zoo import ZOO
    return ZOO


class _LazyZoo(dict):
    def _load(self):
        if not dict.__len__(self):
            self.update(_zoo())

    def __getitem__(self, k):
        self._load(); return dict.__getitem__(self, k)

    def __contains__(self, k):
        self._load(); return dict.__contains__(self, k)

    def __iter__(self):
        self._load(); return dict.__iter__(self)

    def __len__(self):
        self._load(); return dict.__len__(self)

    def keys(self):
        self._load(); return dict.keys(self)

    def items(self):
        self._load(); return dict.items(self)


ZOO = _LazyZoo()


def source_hash(*relpaths) -> str:
    h = hashlib.sha256()
    for rp in relpaths:
        with open(os.path.join(HERE, rp), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def zoo_hash() -> str:
    """The zoo bots are package code: their fingerprint is the fingerprint of the files that define them."""
    return source_hash("controllers/rules_zoo.py", "controllers/rules_ai.py")


def special_bot(kind: str, arg: str, team: str, rules: Rules, seed: int, load):
    """Game-specific spec kinds. `load(spec, team, rules, seed)` loads any other spec (for wrappers).
    Returns a controller, or None if this game does not know the kind."""
    from . import testbots
    if kind == "random":
        return testbots.RandomBot(team, rules, seed)
    if kind == "idle":
        return testbots.IdleBot(team, rules, seed)
    if kind == "noisy":
        mode, p, inner = arg.split(":", 2)
        return testbots.NoisyBot(load(inner, team, rules, seed), mode, float(p), team, rules, seed)
    return None


def make_search(inner_spec: str, opts: dict, team: str, rules: Rules, seed: int):
    """`search[h=..,seeds=..]:<inner>`: the short option names of the spec map onto SearchController's arguments."""
    from .search import OPTION_NAMES, SearchController
    unknown = set(opts) - set(OPTION_NAMES)
    if unknown:
        raise ValueError("unknown search option(s) %s (know: %s)" % (", ".join(sorted(unknown)), ", ".join(OPTION_NAMES)))
    return SearchController(team, rules, seed, base=inner_spec, **{OPTION_NAMES[k]: v for k, v in opts.items()})


def build_llm_bot(cfg: dict, team: str, rules: Rules, seed: int):
    from .llm_bots import build
    return build(cfg, team, rules, seed)


def rules_text(rules: Rules) -> str:
    """The complete rules in words, with every number (what `botkit.py rules` prints and RULES.md holds)."""
    from .rules_doc import rules_text as text
    return text(rules)


def encoder():
    """The value-model state encoder for this game (module with encode_state, FEATURE_NAMES, N_FEATURES)."""
    from . import encode
    return encode


def board():
    """The analysis board's game-specific helpers (ground geometry, words for orders/events, editing, candidates).
    (Not called analysis(): a function named like a submodule gets shadowed by it on import.)"""
    from . import analysis as a
    return a


def install_compat():
    from .compat import install
    install()


def broadcast(ep: dict, **opts) -> dict:
    """The retro broadcast replay as data (frames, plans, chain, ticker, sprites) for the browser's live view."""
    from .render.broadcast import broadcast_data
    return broadcast_data(ep, **opts)


def live_match(**kw):
    """A game you play yourself, in real time (live.py)."""
    import sys
    from .live import LiveMatch
    return LiveMatch(sys.modules[__name__], **kw)


def broadcast_version() -> int:
    from .render.broadcast import VERSION
    return VERSION


def broadcast_sprites() -> dict:
    from .render.broadcast import sprite_sheet
    return sprite_sheet()


def render_video(ep: dict, out: str, **opts):
    from .render.replay import animate
    if out and str(out).lower().endswith(".mp4"):
        from aflsim.video.ffmpeg import use_ffmpeg
        use_ffmpeg()                                                       # the project's own ffmpeg, whatever this process's PATH
    return animate(ep, save=out, **opts)
