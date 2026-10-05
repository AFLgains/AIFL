# Writing a bot

A bot is **one Python file** defining `class Bot`. About once a second (and whenever something happens — a kick,
a mark, a turnover) the engine shows your bot the state of the game and your bot gives each of its players an
order. The engine does everything else: running, energy, kicking with error, contests, scoring.

## The contract

```python
class Bot:
    def __init__(self, team, rules, seed):        # team is "A" or "B"; rules holds every number of the game
        ...
    def choose_actions(self, state, problems):     # -> (intent, [Action, ...])
        ...
```

- Return a short description of the plan (any string) and **at most one `Action` per player**.
- **A player you don't give an order to carries on with its previous order.**
- `problems` lists any of your orders from the previous decision that were invalid (normally empty).
- Your object lives for the whole game: remember anything you like in `self`.
- An exception in your code is caught: your team does nothing that turn, and `afl check` reports it.
- Keep a decision fast — a few milliseconds. (Games run thousands of decisions.)

## The quickest start: build on the base team

`RulesController` (`src/aflsim/games/afl8/controllers/rules_ai.py`) is a complete, sensible team of about 220
lines: man-marking defenders, leading forwards, midfielders who attack the ball, and a ball carrier who shoots in
range, kicks to a leading teammate in space, handballs out of trouble or kicks long. Subclass it and override only
what you want to change:

| Method | Decides |
|---|---|
| `_dispose(me, mine, theirs, set_play)` | what the ball carrier does: shoot, kick to someone, handball, run |
| `_forward(...)`, `_midfielder(...)`, `_defender(...)` | where each line runs when it doesn't have the ball |
| `choose_actions(state, problems)` | everything, if you want a different structure altogether |

The template — **`src/aflsim/bots/botkit_template/my_bot.py`** — does exactly this, with comments. Copy it into
your library and start changing things:

```bash
mkdir -p bots/afl8/code/mine
cp src/aflsim/bots/botkit_template/my_bot.py bots/afl8/code/mine/my_bot.py
```

`src/aflsim/games/afl8/controllers/rules_zoo.py` holds seventeen small example bots, each built around one idea
(a zone defence, long kicking, pressing, running, a goal-square keeper, a defensive wall...). They're the `zoo:`
bots you can play against, and they show how to express an idea in a few dozen lines. Some of those ideas are
good and some are deliberately bad.

## The state your bot sees

```text
state["time"], state["time_left"], state["score"] = {"A": int, "B": int}
state["ball"] = {"state": "held" | "loose" | "flight", "position": [x, y], "velocity": [vx, vy], "owner": "A3" or None,
                 "flight": {...},      # while in the air: kind, from, lands_at, lands_in_s, distance, markable
                 "held_for_s", ...,    # while held
                 "set_play": {...}}    # during a mark or free kick: taker, man_on_the_mark, mark, play_on_called_in_s
state["team_A"] / state["team_B"] = [{"id", "role", "pos", "vel", "energy", "attrs": {...}, "pressure", "moving_to", ...}]
state["goals"] = {"A_scores_at_x": 140.0, "B_scores_at_x": 0.0, "goal_posts_y": [-3.2, 3.2], "behind_posts_y": [-9.6, 9.6]}
state["recent_events"] = [...]          # what happened since your last decision
```

Team A attacks x = 140 and defends x = 0; team B the reverse. In AFL8, A1–A2 are midfielders, A3–A5 defenders and
A6–A8 forwards (the same for B). Player attributes are mirrored between the teams slot for slot, so the only
difference between the sides is the plan.

**Every field, in full:** [`src/aflsim/bots/spec_kit/README.md`](../src/aflsim/bots/spec_kit/README.md) ("The state
you're shown" and "The orders you give").

**The rules, with every number** (kick ranges, mark and spoil chances, energy, set plays): build the kit with
`python afl.py botkit` and read `RULES.md` in the zip it writes to `dist/`, or print them from Python:

```python
from aflsim.games import get_game; g = get_game("afl8"); print(g.rules_text(g.make_rules()))
```

## The orders your bot gives

```python
from aflsim.games.afl8.actions import Action

Action("A6", "MOVE", target=[100, 10], pace="run")      # pace: "sprint" | "run" | "jog"; with the ball: running with it
Action("A6", "KICK", target=[140, 0], power=1.0)        # or target_player="A7"; aim shots at the goal centre
Action("A2", "HANDBALL", target_player="A1")
Action("A3", "ATTEMPT_POSSESSION")                      # go to the ball (or where it lands) and contest it
Action("A4", "ATTEMPT_MARK")  /  Action("A4", "SPOIL")  # contest a kick in the air
Action("A5", "TACKLE", opponent="B7")
Action("A8", "HOLD")                                    # stand still (recovers energy)
```

A `KICK` or `HANDBALL` given to a player who doesn't hold the ball sends him to get it and then dispose of it.

## Test it

```bash
python afl.py check mine/my_bot                                   # loads, gives valid orders, plays a clean game
python afl.py match mine/my_bot zoo:rules --video                 # one game, stored, rendered to video
python afl.py match mine/my_bot zoo:rules --games 50 --both-ends  # a fair series: each seed from both ends
python afl.py rate mine/my_bot                                    # place it on the ladder against a panel
```

`--both-ends` matters: playing each seed from both sides cancels out the luck of the draw, so a series tells you
which bot is better rather than which got the better bounces.

A bot is named by its path in the library: `bots/afl8/code/mine/my_bot.py` is `mine/my_bot`. You can also pass
a path to any `.py` file, or copy a file into the library with `python afl.py add path/to/bot.py --as mine/name`.
Built-in bots are `zoo:<name>` (`python afl.py bots` lists everything with ratings).

## The other style: a standalone bot (`BotBase`)

`src/aflsim/bots/spec_kit/` is a kit for bot-writing competitions: its `bot_base.py` gives you the same helpers
(`self.split(state)`, `self.goal_x`, `self.to_goal(pos)`, `self.kick_range(player)`, ...) **without needing the
engine**, so a friend can write a bot from the kit alone. Bots written that way (`from bot_base import Action,
BotBase`) load in this platform unchanged. `python afl.py botkit` builds that kit as a zip (with `RULES.md`,
example states and a checker) in `dist/`.

## AFL18

The same contract, with 18 players a side on a 160 × 130 m ground. Each player has an archetype — ruck, inside or
outside midfielder, key or running back, tall or small forward — which sets his attributes; it's in his entry in
`state["team_A"]` as `"archetype"`. Run anything with `--game afl18`; library bots live in `bots/afl18/code/`.
