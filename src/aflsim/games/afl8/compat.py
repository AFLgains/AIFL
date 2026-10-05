"""Import aliases so bots written against older kits load unchanged:

  * `afl_llm.*` (the original package: older bots and bot kits written against it)
  * `bot_base` (the analyst botkit's BotBase helpers)

The bot library in this repo imports `aflsim.games.afl8...` directly; the aliases are only for bots from outside.
"""
from __future__ import annotations

import importlib
import sys

_ALIASES = {
    "afl_llm": "aflsim.games.afl8",
    "afl_llm.actions": "aflsim.games.afl8.actions",
    "afl_llm.config": "aflsim.games.afl8.config",
    "afl_llm.ground": "aflsim.games.afl8.ground",
    "afl_llm.physics": "aflsim.games.afl8.physics",
    "afl_llm.players": "aflsim.games.afl8.players",
    "afl_llm.engine": "aflsim.games.afl8.engine",
    "afl_llm.prompts": "aflsim.games.afl8.prompts",
    "afl_llm.controllers": "aflsim.games.afl8.controllers",
    "afl_llm.controllers.base": "aflsim.bots.base",
    "afl_llm.controllers.rules_ai": "aflsim.games.afl8.controllers.rules_ai",
    "afl_llm.controllers.rules_zoo": "aflsim.games.afl8.controllers.rules_zoo",
    "bot_base": "aflsim.games.afl8.bot_base",
    # the engine bundled into analyst workspaces (analyst-written bots import it)
    "afl_engine": "aflsim.games.afl8",
    "afl_engine.actions": "aflsim.games.afl8.actions",
    "afl_engine.config": "aflsim.games.afl8.config",
    "afl_engine.ground": "aflsim.games.afl8.ground",
    "afl_engine.physics": "aflsim.games.afl8.physics",
    "afl_engine.players": "aflsim.games.afl8.players",
    "afl_engine.engine": "aflsim.games.afl8.engine",
    "afl_engine.base": "aflsim.bots.base",
}


def aliases() -> dict:
    """old module name -> the module that serves it now (for tools that rewrite old imports in source)."""
    return dict(_ALIASES)


def install():
    for alias, real in _ALIASES.items():
        if alias not in sys.modules:
            try:
                sys.modules[alias] = importlib.import_module(real)
            except ModuleNotFoundError:                                       # a module this copy doesn't ship: no alias
                pass
