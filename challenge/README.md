# The challenge: beat round_29a

This folder contains a published opponent, the rules for a valid bot, and the grader that measures a bot. Two
games have a target:

| Game | Target | What it is |
|---|---|---|
| **AFL8** (8 a side) | `round_29a` ([`afl8/round_29a.py`](afl8/round_29a.py)) | A strong bot from the agent-driven hill climb. |
| **AFL18** (18 a side) | `zoo:rules` (built into the engine) | The hand-written base team of AFL18. |

The code of each target is public. You can read it, copy it or build on it.

## round_29a

Coding agents made `round_29a` in round 29 of an agent-driven hill climb. In each round, an agent changed the code of
a bot, and the new bot played the strongest bots of the pool. Only the changes that won more games were kept.

`round_29a` does not come from the champion of the climb. An agent wrote it from the start, to play against the
champion of round 28. The docstring at the top of the file explains each part. In summary:

1. **Energy.** Players jog to their positions. Only one player chases the ball carrier. The team stays fresh.
2. **Races.** The bot calculates who gets to a loose ball first. The calculation includes each player's energy.
3. **Defence.** The bot uses a compact zone that moves with the ball.
4. **The flood.** When the opponent has the ball, two forwards move back 22 to 42 m in front of the ball carrier.
   Each forward stands where the opponent's kick is most likely to go. The flood starts only after an opponent
   holds the ball for 2 seconds or more at a set play.
5. **Attack.** The bot handballs to free teammates, runs when no opponent is near, and kicks only to a teammate who
   gets to the ball first.

## Quick start

Install the platform ([docs/setup.md](../docs/setup.md)), then write a bot ([docs/writing-bots.md](../docs/writing-bots.md)).

```bash
python challenge/grade.py path/to/my_bot.py --quick              # a fast check: 40 games, no rating
python challenge/grade.py path/to/my_bot.py                      # the full grade, AFL8
python challenge/grade.py path/to/my_bot.py --game afl18         # the full grade, AFL18
python afl.py match path/to/my_bot.py challenge/afl8/round_29a.py --video    # watch one game
```

On Windows, use `.venv\Scripts\python` in place of `python`.

## The rules for a valid bot

1. The bot is **one Python file** that defines `class Bot(team, rules, seed)`. The contract is in
   [docs/writing-bots.md](../docs/writing-bots.md).
2. The bot can import the Python standard library, `numpy`, and the public modules of `aflsim`. It can subclass or
   copy any public bot, including the target.
3. The bot must use only the state that the engine gives it. It must not:
   - read or write files, use the network, or start processes or threads;
   - find or change the opponent's bot, the engine, the game object, or the rules (for example, with `gc`,
     `sys.modules`, `inspect` or stack frames);
   - define `observe_game` (the hook that gives a search bot the true game object).
4. The bot must be **deterministic**. The same seed must give the same game. Use the `seed` argument for all
   random numbers.
5. The bot must give **no errors**. An error in a decision is a lost turn, and one error makes the grade invalid.
6. The bot must be fast:
   - mean time per decision: **50 ms** or less;
   - longest single decision: **1,000 ms** or less.

   For comparison, `round_29a` uses about 0.4 ms per decision.

The grader checks rules 3 (the `observe_game` part), 4, 5 and 6. For an official grade, a person also reads the code
for rules 1 to 3.

## How the grader measures a bot

All games are 240 seconds long (the standard length), on the current engine (AFL8 engine v2, AFL18 engine v1). The
grader writes nothing to your results store.

### 1. The match: the win rate against the target

1. The bot plays the target on **200 seeds**.
2. Each seed is played **from both ends**: once as team A and once as team B. The total is **400 games**.
3. The win rate is (wins + ½ × draws) ÷ 400.
4. The bot **beats the target** if its win rate is **55 % or more**.

At 55 %, the lower end of the 95 % interval is above 50 %. Thus a win rate of 55 % is very unlikely to come from
luck alone.

### 2. The rating: Elo against a fixed pool

The win rate shows the result against one opponent. The rating shows the strength against many opponents.

1. The **reference pool** is the target and all the public zoo bots: 18 bots for AFL8, 12 bots for AFL18.
2. Before the challenge, each pair of pool bots played 40 games (20 seeds from both ends). A Bradley–Terry fit (the
   model behind Elo) gave each pool bot a rating. The five anchor bots of each game have a mean of exactly 1,500.
   The ratings are in `<game>/reference.json` and they do not change.
3. Your bot plays each pool bot other than the target on **20 seeds from both ends** (40 games each). The 400 match
   games against the target are also used.
4. The grader calculates the one rating that best agrees with all these results, with the pool ratings fixed. It
   also gives a 95 % interval.

A difference of 200 points means that the stronger bot scores about 76 %. These ratings use only the public pool.
They are not on the same scale as other ladders in this project.

### 3. Self-test seeds and official seeds

The self-test seeds are 1 to 200, and they are public. You can use them as often as you like.

For an **official grade**, the maintainer runs the same grader with a secret first seed (`--seed0`). The secret seed
is chosen at random at the time of grading. After the grade, the maintainer publishes the seed, so anyone can run
the grade again and get the same result. Thus, a bot that is tuned to the public seeds gets no advantage.

## Results

| Bot | Game | Win rate against the target | Rating (95 % interval) |
|---|---|---|---|
| `round_29a` (the target, against itself) | AFL8 | 50 % | *(after the pool is built)* |
| `zoo:rules` (the target, against itself) | AFL18 | 50 % | *(after the pool is built)* |

To submit a bot for an official grade, open an issue on this repository and attach the bot file. Give your result
on the self-test seeds.
