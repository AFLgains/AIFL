"""`afl botkit`: build the zip handed to outside bot writers.

    afl botkit           the TOURNAMENT kit (default, dist/aifl_bot_tournament.zip): no simulator and none of the league's
                         code; the bot interface, the rules, a template, a standalone bot_base.py and a test suite
                         (check_bot.py) that shows a bot hundreds of real recorded situations and checks every answer
    afl botkit --full    the full kit (dist/aifl_botkit.zip): also the match engine, so a writer can play games locally

The full kit's description follows. It is generated from the live package every time, so the
kit can never drift from the engine the league runs (the old hand-made zip did).

Contents: the parts of the `aflsim` package a bot writer needs (the engine, the rules, the example zoo bots, the
match / ladder / rating tools, the renderer), the kit's README, a `my_bot.py` template, `botkit.py` (a thin front on
`aflsim.cli`) and requirements.txt.

Deliberately NOT shipped (not needed to write or test a bot): the bot library (bots/ at the repo root is never
packaged), results, and everything beyond the engine and the tools listed above.
"""
from __future__ import annotations

import os
import zipfile

from aflsim import paths

EXCLUDE_DIRS = {"__pycache__", "analyst", "rl", "botkit_template", "app", "analysis", "value"}
EXCLUDE_FILES = {"search.py", "encode.py", "analysis.py", "llm_bots.py", "llm.py", "coached.py", "jev.py", "prompts_coached.py", "teampack.py"}


def build(out: str | None = None, game: str = "afl8") -> str:
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))            # src/aflsim
    tmpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "botkit_template")
    out = out or os.path.join(paths.home(), "dist", "aifl_botkit.zip")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(tmpl)):
            z.write(os.path.join(tmpl, f), "aifl_botkit/" + f)
        for root, dirs, files in os.walk(pkg):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if f.endswith((".pyc",)) or f in EXCLUDE_FILES:
                    continue
                full = os.path.join(root, f)
                z.write(full, "aifl_botkit/aflsim/" + os.path.relpath(full, pkg).replace(os.sep, "/"))
    return out


# ------------------------------------------------------------------ the tournament kit: no engine, no league code
SPEC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spec_kit")
SPEC_FILES = ("README.md", "my_bot.py", "random_bot.py", "check_bot.py")


def record_states(game: str = "afl8", games=(("zoo:zone", "zoo:press", 1), ("zoo:keeper", "zoo:boundary", 2), ("zoo:runner", "zoo:wall", 3)),
                  cap: int = 360) -> list:
    """Real decision-point states from a few games between the simple example bots: every one with the ball in the
    air or a set play, and a regular sample of the rest."""
    import copy
    import json
    from aflsim.bots.registry import load_bot
    from aflsim.engine import run_match
    from aflsim.games import get_game
    g = get_game(game); rules = g.make_rules(); seen = []
    for a, b, seed in games:
        run_match(g, load_bot(a, "A", rules, seed, game), load_bot(b, "B", rules, seed + 500, game), rules, seed, record="none",
                  on_state=lambda _g, st: seen.append(json.loads(json.dumps(st, default=float))))
    kind = lambda st: "set play" if st["ball"].get("set_play") else st["ball"].get("state")
    groups = {}
    for st in seen:
        groups.setdefault(kind(st), []).append(st)
    each = cap // max(1, len(groups)); out = []
    for k in sorted(groups):                                                # an even spread of each kind, across the games
        g_ = groups[k]; step = max(1, len(g_) // each)
        out += g_[::step][:each]
    return copy.deepcopy(out)


def build_spec(out: str | None = None, game: str = "afl8") -> str:
    """The tournament kit: see the module docstring. The game's numbers are baked into bot_base.py and RULES.md."""
    import dataclasses
    import json
    from aflsim.games import get_game
    g = get_game(game); rules = g.make_rules()
    out = out or os.path.join(paths.home(), "dist", "aifl_bot_tournament.zip")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    base = open(os.path.join(SPEC_DIR, "bot_base.py"), encoding="utf-8").read()
    marker = "_RULES = {}"
    assert marker in base
    numbers = dataclasses.asdict(rules)
    for name in dir(type(rules)):                                           # computed numbers too (kick ranges, team size)
        if isinstance(getattr(type(rules), name), property):
            numbers[name] = getattr(rules, name)
    base = base.replace(marker, "_RULES = " + repr(numbers), 1)
    rules_md = ("# The rules of the game\n\nThe complete rules, with every number. Every number here is also available in your bot "
                "as an attribute of `self.r` (e.g. `self.r.length`).\n\n```\n" + g.rules_text(rules) + "\n```\n")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in SPEC_FILES:
            z.write(os.path.join(SPEC_DIR, f), "aifl_bot_tournament/" + f)
        z.writestr("aifl_bot_tournament/bot_base.py", base)
        z.writestr("aifl_bot_tournament/RULES.md", rules_md)
        z.writestr("aifl_bot_tournament/states.json", json.dumps(record_states(game)))
    return out
