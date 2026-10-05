"""afl18: 18-a-side Australian Rules on a full-size (160 x 130 m) oval, with player archetypes. The game contract the
shared machinery talks to (see aflsim.games).

The laws, physics and engine are afl8's (engine v2): only the ground, the line-up (6 midfielders: 1 ruck, 3 inside,
2 outside; 6 forwards: 2 tall, 4 small; 6 backs: 2 key, 4 running) and the archetype attribute profiles differ (see
config.py). There is no value model for afl18 yet, so there is no look-ahead (search:) bot and the analysis tools
that rate positions don't apply; LLM teams aren't set up for it yet either.
"""
from __future__ import annotations

import hashlib
import os

from aflsim.games.afl8 import action_exact, action_from_dict, install_compat, special_bot  # noqa: F401
from aflsim.games.afl8.actions import Action, action_to_dict, parse_actions  # noqa: F401

from .config import Rules
from .engine import Game

NAME = "afl18"
ENGINE_VERSION = 1          # 1: afl8 engine v2's laws on the 160 x 130 m ground, 18 a side, archetypes
DEFAULT_SECONDS = 240.0
ANCHORS = ("rules", "zone", "press", "keeper", "runner")                   # rating anchors, pinned to average 1500
HERE = os.path.dirname(os.path.abspath(__file__))
AFL8 = os.path.join(os.path.dirname(HERE), "afl8")


def make_rules(seconds: float | None = None, **overrides) -> Rules:  # one engine so far: no OLD_ENGINES
    return Rules(episode_seconds=float(seconds or DEFAULT_SECONDS), **overrides)


def mirror_attributes(game):
    """Fair setup: team B's player k gets exactly team A's player k's attributes."""
    for i in range(game.r.n_per_team):
        game.players["B%d" % (i + 1)].attrs = dict(game.players["A%d" % (i + 1)].attrs)


def new_game(rules: Rules, seed: int, mirror: bool = True) -> Game:
    g = Game(rules, seed)
    if mirror:
        mirror_attributes(g)
    return g


class _LazyZoo(dict):
    def _load(self):
        if not dict.__len__(self):
            from .controllers.zoo import ZOO as Z
            self.update(Z)

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
        with open(rp if os.path.isabs(rp) else os.path.join(HERE, rp), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def zoo_hash() -> str:
    """The zoo bots are afl8's rules bots, chosen in controllers/zoo.py: their fingerprint covers all three files."""
    return source_hash(os.path.join(AFL8, "controllers", "rules_zoo.py"), os.path.join(AFL8, "controllers", "rules_ai.py"), "controllers/zoo.py")


def make_search(inner_spec: str, opts: dict, team: str, rules: Rules, seed: int):
    raise ValueError("afl18 has no value model yet, so no look-ahead (search:) bots")


def build_llm_bot(cfg: dict, team: str, rules: Rules, seed: int):
    raise ValueError("LLM teams aren't set up for afl18 yet")


def rules_text(rules: Rules) -> str:
    from aflsim.games.afl8.prompts import rules_text as text
    return text(rules)


def encoder():
    raise NotImplementedError("afl18 has no value model yet")


def board():
    from . import analysis as a
    return a


def broadcast(ep: dict, **opts) -> dict:
    from aflsim.games.afl8 import broadcast as b8
    return b8(ep, **opts)


def live_match(**kw):
    import sys
    from aflsim.games.afl8.live import LiveMatch
    return LiveMatch(sys.modules[__name__], **kw)


def broadcast_version() -> int:
    from aflsim.games.afl8 import broadcast_version as v8
    return v8()


def broadcast_sprites() -> dict:
    from aflsim.games.afl8 import broadcast_sprites as s8
    return s8()


def render_video(ep: dict, out: str, **opts):
    from aflsim.games.afl8 import render_video as rv8
    return rv8(ep, out, **opts)
