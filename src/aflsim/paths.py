"""Every location the package reads or writes, in one place. Nothing else in the code builds a path to a data folder.

The root is `AFL_HOME` if set (a cloud machine, a test's temporary folder), else the repo this package sits in.
Per-game data is split by game name ("afl8" today; "afl18" later), so two games never share a store or a model.
"""
from __future__ import annotations

import os

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # src/aflsim/paths.py -> repo


def home() -> str:
    return os.path.abspath(os.environ.get("AFL_HOME") or _REPO)


def repo() -> str:
    """The source checkout (for the bundled bot library and templates), independent of AFL_HOME."""
    return _REPO


def _mk(p):
    os.makedirs(p, exist_ok=True)
    return p


def bots_dir(game: str) -> str:
    """The bot library. Lives in the repo (it is versioned), unless AFL_BOTS points elsewhere."""
    return os.path.abspath(os.environ.get("AFL_BOTS") or os.path.join(_REPO, "bots", game))


def models_dir(game: str) -> str:
    return os.path.abspath(os.environ.get("AFL_MODELS") or os.path.join(_REPO, "models", game))


def results_db(game: str) -> str:
    return os.path.join(_mk(os.path.join(home(), "results")), "%s.sqlite" % game)


def logs_dir(game: str) -> str:
    return _mk(os.path.join(home(), "results", "logs", game))


def videos_dir(game: str) -> str:
    return _mk(os.path.join(home(), "videos", game))


def data_dir(game: str) -> str:
    return _mk(os.path.join(home(), "data", game))


def tournaments_dir() -> str:
    """Tournament configs (versioned, in the repo). AFL_TOURNAMENTS redirects them (tests)."""
    return os.path.abspath(os.environ.get("AFL_TOURNAMENTS") or os.path.join(_REPO, "tournaments"))


def experiments_dir() -> str:
    """Experiment records (versioned, in the repo). AFL_EXPERIMENTS redirects them (tests use a temporary folder)."""
    return os.path.abspath(os.environ.get("AFL_EXPERIMENTS") or os.path.join(_REPO, "experiments"))


def analyst_root() -> str:
    """Where analyst workspaces are built: deliberately OUTSIDE the repo, so an agent confined there cannot read it."""
    return os.path.abspath(os.environ.get("AFL_ANALYST_ROOT") or os.path.join(os.path.dirname(_REPO), "afl_analysis_runs"))
