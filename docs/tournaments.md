# Tournaments

A tournament is a TOML file in `tournaments/`. Every pairing plays `seeds` seeds, **each from both ends** (so luck
of the draw cancels out), and every game is stored, tagged with the tournament — so a stopped tournament resumes
where it left off when you run it again.

```bash
python afl.py tournament tournaments/weekend_cup.toml            # run (or resume) it
python afl.py tournament tournaments/weekend_cup.toml --dry-run  # how many games it would play
python afl.py tournament-status weekend_cup                      # the standings
```

(Or build and run one in the app: **Play → Tournaments**.)

## The config

```toml
name = "weekend_cup"          # unique: running the same name again resumes it
format = "round_robin"        # round_robin | groups | gauntlet | ladder
seconds = 240                 # game length
seeds = 5                     # per pairing (x2 for both ends)
seed = 100000                 # base seed: each pairing derives its own from the two names
logs = false                  # keep full game logs (videos without re-simulating)
bots = ["mine/my_bot", "mine/other_bot", "zoo:rules", "zoo:ontario"]
```

The formats:

| `format` | Extra keys | What happens |
|---|---|---|
| `round_robin` | `bots = [...]` | everyone plays everyone |
| `groups` | `[groups]` with `A = [...]`, `B = [...]`, ... and `finals = 2` | a round robin in each group; the top `finals` of each play a final round robin |
| `gauntlet` | `challenger = "<bot>"`, `field = [...]` or `field = "library"` | one bot plays every bot in the field |
| `ladder` | `bots = "library"` or a list | everyone plays everyone; the result is a rating ladder |

For AFL18, run it with `python afl.py --game afl18 tournament ...` (the app does this for you when the top bar is on
AFL18).

## Standings and ratings

Standings are AFL-style: **4 premiership points for a win, 2 for a draw**, then **percentage** (points for ÷
points against × 100). Every table also carries **ratings**: a Bradley–Terry fit (the model behind Elo) over the
tournament's games, centred so that the built-in anchor bots average 1500. A rating gap of 200 means the
stronger bot scores about 76 % against the weaker.

An example config: [`docs/examples/weekend_cup.toml`](examples/weekend_cup.toml). Copy it into `tournaments/`.
