"""Bot kit command line: rules, check, play, ladder, results, render. A thin front on the league's own `aflsim` package,
so what you test here is exactly what the league runs.

    python botkit.py rules                                   # print the complete rules of the game
    python botkit.py check my_bot.py                         # load a bot as both teams, play the rules bot, report errors
    python botkit.py play my_bot.py zoo:zone --games 20      # a series, every seed from both ends
    python botkit.py ladder my_bot.py --games 6              # your bot against every example bot
    python botkit.py results                                 # your stored games
    python botkit.py render 12                               # video of stored game 12 (needs ffmpeg)
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("AFL_HOME", HERE)                                    # results, logs and videos stay inside the kit


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    cmd, rest = argv[0], argv[1:]
    from aflsim.cli import main as afl
    if cmd == "rules":
        from aflsim.games.afl8 import make_rules
        from aflsim.games.afl8.prompts import rules_text
        print(rules_text(make_rules())); return 0
    if cmd == "check":
        return afl(["check", os.path.abspath(rest[0])] + rest[1:])
    if cmd == "play":
        games = rest[rest.index("--games") + 1] if "--games" in rest else "10"
        bots = [os.path.abspath(b) if b.endswith(".py") else b for b in rest[:2]]
        return afl(["match", bots[0], bots[1], "--games", games, "--both-ends", "--no-log"] + [x for x in rest[2:] if x not in ("--games", games)])
    if cmd == "ladder":
        from aflsim.games.afl8 import ZOO
        games = rest[rest.index("--games") + 1] if "--games" in rest else "6"
        me = os.path.abspath(rest[0])
        for z in sorted(ZOO):
            afl(["match", me, "zoo:" + z, "--games", games, "--both-ends", "--no-log"])
        return 0
    if cmd == "results":
        return afl(["results"] + rest)
    if cmd == "render":
        return afl(["render"] + rest)
    print(__doc__); return 1


if __name__ == "__main__":
    sys.exit(main())
