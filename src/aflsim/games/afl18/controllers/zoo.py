"""afl18's zoo: afl8's rules bots that work by line (midfielders / forwards / defenders) and so play 18 a side as
they are. The archetype-aware bots live in the library (bots/afl18/code)."""
from aflsim.games.afl8.controllers.rules_zoo import ZOO as ZOO8

NAMES = ("rules", "zone", "press", "keeper", "runner", "defence", "lead", "spoiler", "boundary", "stack", "rusher", "handball")
ZOO = {k: ZOO8[k] for k in NAMES if k in ZOO8}
