# AIFL bot kit: write a scripted team for the 8-a-side AFL simulator

You write one Python file that decides, once a second, what each of your eight players does. The simulator
does the rest: physics, contests, scoring, energy. Your bot plays against other bots; no language model is
involved at runtime, so games take about a second and you can test thousands.

This kit contains the full simulator (`aflsim/`, the same package the league runs), a base team to build on, a set of simple example bots, a
template, and a command-line tool to test your bot and render games to video.

## Setup

Python 3.11 or newer. From this folder:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt        # Windows;  .venv/bin/pip on Mac / Linux
.venv\Scripts\python botkit.py check my_bot.py
```

Videos need `ffmpeg` on the PATH (only for `botkit.py render`).

## The game in one paragraph

Two teams of eight (2 midfielders, 3 defenders, 3 forwards) on a 140 x 100 m oval, 240 seconds of play (4-minute games).
Team A scores at x = 140 and defends x = 0; team B the reverse. A goal is 6 points and restarts play with a
centre ball-up; a behind is 1 point and the defending side kicks in from the goal square. Kicks can be marked
(a set play with a man on the mark if an opponent is close), spoiled, or spilled to the ground; handballs are
short and accurate and never marked. A tackled carrier who had time to dispose of the ball gives away a free
kick. Every player has energy: sprinting drains it, standing or jogging restores it, and a tired player is slow.
Player attributes (speed, kicking, marking...) are mirrored between the two teams slot for slot, so the only
difference between the sides is the plan.

The complete rules, with every number, are printed by:

```
.venv\Scripts\python botkit.py rules
```

Read that once. It is the same text the simulator's language-model teams are given, and it is authoritative.

## The file you write

Copy `my_bot.py` and edit it. It must define `class Bot` with `__init__(self, team, rules, seed)` and
`choose_actions(self, state, problems)` returning `(intent_string, [Action, ...])`, at most one Action per
player. The easiest route is to subclass `RulesController` (in `aflsim/games/afl8/controllers/rules_ai.py`), a
complete, sensible team of about 220 lines, and override the pieces you want to change:

- `_dispose(self, me, mine, theirs, set_play)`: what the ball carrier does (shoot, kick to a lead, handball, run).
- `_forward(...)`, `_midfielder(...)`, `_defender(...)`: where each role runs when it does not have the ball.
- `choose_actions(...)` itself, if you want a different structure altogether.

`aflsim/games/afl8/controllers/rules_zoo.py` holds seventeen small example bots, each built around one idea (a zone
defence, long kicking, pressing, running, a goal-square keeper, a defensive wall...). They show how to
express an idea in a few dozen lines. Some of those ideas are good and some are deliberately bad; find out
which by playing them.

Exceptions in your code are caught (your team does nothing that turn) and reported by `botkit.py check`.

## The state you receive

```
state["time"], state["time_left"], state["score"] = {"A": int, "B": int}
state["ball"] = {"state": "held" | "loose" | "flight", "position": [x, y], "velocity": [vx, vy], "owner": "A3" or None,
                 "flight": {"kind": "kick" | "handball", "from": "B2", "lands_at": [x, y], "lands_in_s": float, "distance": float, "markable": bool},   # in the air
                 "held_for_s": float, "run_since_bounce_m": float, "run_this_possession_m": float,          # while held
                 "set_play": {"taker": "A5", "man_on_the_mark": "B1" or None, "mark": [x, y], "play_on_called_in_s": float}}   # during a set play
state["team_A"] / state["team_B"] = [{"id": "A1", "role": "midfielder" | "defender" | "forward", "pos": [x, y], "vel": [vx, vy],
                                     "energy": 0..1, "attrs": {"speed", "acceleration", "endurance", "kick_power", "kick_accuracy",
                                     "handball_power", "handball_accuracy", "marking_skill", "ground_ball_skill", "tackling_skill"},   # all 0..1
                                     "pressure": 0..2, "moving_to": [x, y] or None, "standing_the_mark": True (if frozen)}]
state["goals"] = {"A_scores_at_x": 140.0, "B_scores_at_x": 0.0, "goal_posts_y": [-3.2, 3.2], "behind_posts_y": [-9.6, 9.6]}
```

`self.team` is "A" or "B". You see both teams' attributes and energy, as a coach would.

## Actions

- `Action(pid, "MOVE", target=[x, y], pace="run")`: pace is "sprint", "run" (default) or "jog". With the ball, this is running with it.
- `Action(pid, "KICK", target=[x, y], power=0..1)`: a kick towards the target. Aim shots at `[goal_x, 0]`.
- `Action(pid, "HANDBALL", target_player="A4")` or `target=[x, y]`.
- `Action(pid, "ATTEMPT_MARK")`, `"SPOIL"`, `"ATTEMPT_POSSESSION"`: go to the ball and contest it.
- `Action(pid, "TACKLE", opponent="B3")`.
- `Action(pid, "HOLD")`: stand still (and recover energy).

The distances, error models, contest odds and energy rates behind these are all in the rules text.

## Testing

```
.venv\Scripts\python botkit.py check my_bot.py                       # loads it as both teams, plays the rules bot, reports errors and speed
.venv\Scripts\python botkit.py play my_bot.py zoo:zone --games 20     # a series against an example bot, every seed from both ends
.venv\Scripts\python botkit.py play my_bot.py other_bot.py --games 20 # any two bot files
.venv\Scripts\python botkit.py ladder my_bot.py --games 6             # your bot against every example bot: a ladder
.venv\Scripts\python botkit.py results                               # every game you have played (stored in results/)
.venv\Scripts\python botkit.py render 12                              # an MP4 of stored game #12 (videos/afl8/12.mp4)
```

Every game is stored in `results/afl8.sqlite` inside the kit, with its full log in `results/logs/`.

Two things every strong bot author here has learned the hard way: games are decided by a handful of events,
so a six-game series between similar bots is a coin flip; use twenty games per opponent at least. And a
change that wins on one set of seeds often loses on another; confirm on fresh seeds (`--seed`) before you
believe it.

Game logs are gzipped JSON with `events` (every kick, mark, spoil, tackle, possession, turnover and score, with
positions and times) and `frames` (every player's position and energy through the game). When you lose,
read them.

## Submitting

Send back your single `.py` file (it may only import from `aflsim` and the standard library, plus numpy. Bots written for the older kit (`from afl_llm...`) still load).
It will be played against the other entrants and the example bots, both ends, many games, and rated.
