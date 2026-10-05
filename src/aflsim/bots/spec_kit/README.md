# AIFL bot tournament: write a team

You write **one Python file** that coaches a team of eight in an 8-a-side Australian Rules football simulator:
about once a second (and straight after anything important happens) it is shown the whole game state and gives
each of its players an order. The organiser plays every entry against every other in the league's match engine.

## What's in this folder

| File | What it is |
|---|---|
| `README.md` | this: the bot interface, the state you see, the orders you give |
| `RULES.md` | the complete rules of the game, with every number (ground, kicks, marks, tackles, energy) |
| `my_bot.py` | a very simple starting bot: copy it and make it good |
| `random_bot.py` | a random team (a second example) |
| `bot_base.py` | `Action`, `BotBase` (geometry helpers) and the game's numbers: import from here |
| `check_bot.py` | the test suite: checks your bot is sound before you send it |
| `states.json` | real game situations the test suite shows your bot |

There is no match engine in this folder: you can't play games here. You write your bot from the rules, test that it
is sound with `check_bot.py`, and send it in.

## Setup and testing

Python 3.10 or newer, and numpy:

```
python -m pip install numpy
python check_bot.py my_bot.py
```

`check_bot.py` shows your bot a few hundred real situations (ball held, loose, in the air, set plays, from both
ends) and checks every answer: that it loads, never crashes, only gives valid orders, doesn't change the state it's
given, is quick enough and answers the same way given the same seed. It prints PASS or FAIL with the reasons.
Only submit a bot that passes.

## Submitting

Send the organiser your single `.py` file. Rules for the file:

- it defines `class Bot` (see below) and imports only from `bot_base`, `numpy` and plain standard-library maths
  helpers (`math`, `random`, `collections`, `itertools`, `functools`, `dataclasses`, `typing`, `heapq`, `bisect`,
  `statistics`, `enum`, `copy`, `operator`);
- no files, network, subprocesses, threads or `eval`/`exec`;
- keep it quick: well under 100 ms per decision on average (most bots take under 1 ms);
- use `self.rng` (a numpy random generator seeded for you) for any randomness, so games can be replayed.

## The game in one paragraph

Two teams of eight (2 midfielders, 3 defenders, 3 forwards) on a 140 x 100 m oval, four-minute games. Team A scores
at x = 140 and defends x = 0; team B the reverse (you play both ends during the tournament: the helpers below handle
direction for you). A goal is 6 points and restarts play with a centre ball-up; a behind is 1 point and the defending
side kicks in. Kicks can be marked (a set play), spoiled or spilled; handballs are short and accurate and never
marked. A tackled carrier who had time to dispose of the ball gives away a free kick. Sprinting drains energy,
standing or jogging restores it, and a tired player is slow. Player attributes are mirrored between the two teams
slot for slot, so the only difference between the sides is the plan. **Read `RULES.md` once: it is authoritative.**

## Your bot

```python
from bot_base import Action, BotBase

class Bot(BotBase):
    def __init__(self, team, rules, seed=0):
        super().__init__(team, rules, seed)          # sets self.team ("A" or "B"), self.r (the game's numbers), self.rng
        self.name = "my_bot"

    def choose_actions(self, state, problems):
        mine, theirs, ball, holder = self.split(state)
        acts = [...]                                  # at most one Action per player
        return "a short description of the plan", acts
```

`choose_actions` returns `(intent, [Action, ...])`. **A player you don't give an order to carries on with its
previous order.** `problems` lists any of your orders from the previous turn that were invalid (normally empty).
Your object lives for the whole game, so you can remember things between decisions in `self`.

## The state you're shown

```
state["time"], state["time_left"], state["score"] = {"A": int, "B": int}
state["ball"] = {"state": "held" | "loose" | "flight", "position": [x, y], "velocity": [vx, vy], "owner": "A3" or None,
                 "flight": {"kind": "kick" | "handball", "from": "B2", "lands_at": [x, y], "lands_in_s": float,
                            "distance": float, "markable": bool},                                   # while in the air
                 "held_for_s": float, "run_since_bounce_m": float, "run_this_possession_m": float,  # while held
                 "set_play": {"taker": "A5", "man_on_the_mark": "B1" or None, "mark": [x, y],
                              "play_on_called_in_s": float}}                                        # during a set play
state["team_A"] / state["team_B"] = [{"id": "A1", "role": "midfielder" | "defender" | "forward", "pos": [x, y],
                                     "vel": [vx, vy], "energy": 0..1,
                                     "attrs": {"speed", "acceleration", "endurance", "kick_power", "kick_accuracy",
                                               "handball_power", "handball_accuracy", "marking_skill",
                                               "ground_ball_skill", "tackling_skill"},              # all 0..1
                                     "pressure": 0..2, "moving_to": [x, y] or None, "standing_the_mark": True/False}]
state["goals"] = {"A_scores_at_x": 140.0, "B_scores_at_x": 0.0, "goal_posts_y": [-3.2, 3.2], "behind_posts_y": [-9.6, 9.6]}
state["recent_events"] = [...]   # what happened since your last decision (kicks, marks, tackles, scores...)
```

Player ids: A1-A2 midfielders, A3-A5 defenders, A6-A8 forwards (the same for B). Open `states.json` to see real
examples. x runs along the ground (0 to 140), y across it (-50 to 50).

## The orders you give

- `Action(pid, "MOVE", target=[x, y], pace="run")`: pace is `"sprint"`, `"run"` or `"jog"`. With the ball, this is
  running with it.
- `Action(pid, "KICK", target=[x, y], power=0..1)`: a kick towards the target (or `target_player="A6"` to kick to a
  teammate). Aim shots at `[self.goal_x, 0]`.
- `Action(pid, "HANDBALL", target_player="A4", power=...)` or `target=[x, y]`.
- `Action(pid, "ATTEMPT_POSSESSION")`: go to the ball (or where it will land) and contest it.
- `Action(pid, "ATTEMPT_MARK")` / `Action(pid, "SPOIL")`: contest a kick in the air: mark it, or punch it away.
- `Action(pid, "TACKLE", opponent="B3")`: chase and tackle.
- `Action(pid, "HOLD")`: stand still (and recover energy).

A KICK or HANDBALL given to a player who doesn't hold the ball yet sends them to get it and then dispose of it.

## Helpers in `BotBase`

`self.split(state)` gives `(mine, theirs, ball, holder)`; `self.by_role(players)`; `self.goal_x` / `self.own_x` (the
goal lines you attack / defend); `self.ahead(x, m)` (x moved m metres towards your goal); `self.to_goal(pos)`;
`self.dist(a, b)`; `self.clip(x, y)` (the nearest point on the ground); `self.kick_range(player)` (its full-power kick
distance); `self.r` (every number in RULES.md, e.g. `self.r.length`); `self.rng`.
