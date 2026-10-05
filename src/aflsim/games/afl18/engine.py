"""afl18's game: afl8's engine (every law, physic and rule), with afl18's archetype attribute profiles."""
from __future__ import annotations

from aflsim.games.afl8.engine import Game as Game8

from .config import PROFILES, Rules


class Game(Game8):
    PROFILES = PROFILES

    def __init__(self, rules: Rules = Rules(), seed: int = 0, attrs: dict | None = None):
        super().__init__(rules, seed, attrs)
