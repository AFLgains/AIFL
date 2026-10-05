"""The afl8 controllers: the rules AI and its zoo of variants, simple baselines, and the LLM-driven teams.
(The game-agnostic TeamController base lives in aflsim.bots.base.)"""
from aflsim.bots.base import TeamController

from .baselines import HeuristicController, RandomController
from .rules_ai import DefensiveRulesController, RulesController

try:                                                                         # the LLM teams (not shipped in the bot kit)
    from .coached import CoachedTeamController
    from .llm import LLMController
except ImportError:                                                          # pragma: no cover  (only in the bot kit)
    CoachedTeamController = LLMController = None

__all__ = ["TeamController", "HeuristicController", "RandomController", "LLMController", "CoachedTeamController", "RulesController", "DefensiveRulesController"]
