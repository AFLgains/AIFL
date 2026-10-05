# afl_sim — an Australian Rules football simulator for bots (and you)

A physics engine for Australian Rules football, built for **writing bots that play it**. Two games:

| Game | Players | Ground | Notes |
|---|---|---|---|
| **AFL8** | 8 a side (2 midfielders, 3 defenders, 3 forwards) | 140 × 100 m oval | the main game; engine v2 (v1 still playable) |
| **AFL18** | 18 a side (ruck, inside/outside mids, key/running backs, tall/small forwards) | 160 × 130 m oval | the same laws, more players, player archetypes |

The engine simulates the whole game: running and energy, kicks with real flight and error, marks and spoils,
contested ground balls, tackles and holding the ball, set plays with a man on the mark, goals and behinds. A bot
is one Python file that gives each of its players an order about once a second; a 4-minute game takes about a
second to play, so you can test thousands of them.

What's in this repository:

- **The engine** (`src/aflsim/games/`): AFL8 and AFL18 — rules, physics, players, the oval.
- **The match machinery**: play matches and series, run tournaments (round robin, groups, gauntlet, ladder),
  Elo-style ratings, a results store, replay videos.
- **A web app**: build and browse bots, play matches and tournaments, browse results, watch any game as a retro
  16-bit broadcast — and **play it yourself** against a bot, on the keyboard.
- **Bot templates**: a commented starting bot, a base team to build on, seventeen small example bots, and a
  standalone kit for bot-writing competitions.

## Quick start

You need **Python 3.11 or newer** (3.13 recommended). Nothing else: the database is SQLite, which is built into
Python, and video encoding uses an ffmpeg that is installed with the app's Python packages.

```bash
git clone <this repo> afl_sim
cd afl_sim
python -m venv .venv
.venv/bin/pip install -e ".[app]"          # Windows: .venv\Scripts\pip install -e ".[app]"
```

Play a game between two built-in bots and render it to video:

```bash
.venv/bin/python afl.py match zoo:rules zoo:zone --video
```

Start the web app (then open http://127.0.0.1:8765):

```bash
.venv/bin/python afl.py app                # Windows: double-click run_app.bat
```

Full instructions, including what gets installed and where everything is stored: **[docs/setup.md](../docs/setup.md)**.

## Write a bot

```bash
mkdir -p bots/afl8/code/mine
cp src/aflsim/bots/botkit_template/my_bot.py bots/afl8/code/mine/my_bot.py
.venv/bin/python afl.py check mine/my_bot                 # loads? valid orders? plays a clean game?
.venv/bin/python afl.py match mine/my_bot zoo:rules --games 20 --both-ends
```

The guide — the contract, the state your bot sees, the orders it gives, the base team you can build on, and how
to test: **[docs/writing-bots.md](../docs/writing-bots.md)**.

## More

- **[docs/app.md](../docs/app.md)** — the web app, section by section, and the controls for playing yourself.
- **[docs/tournaments.md](../docs/tournaments.md)** — tournament configs (TOML), formats, standings and ratings.
- **[docs/setup.md](../docs/setup.md)** — installation, the folders the platform writes, settings, troubleshooting.

## The command line, at a glance

```text
python afl.py match A B [--games N --both-ends --seconds S --seed K --video]   play a match or a series
python afl.py tournament tournaments/my_cup.toml                                 run (or resume) a tournament
python afl.py rate mine/my_bot                                                   place a bot on the ladder
python afl.py ladder                                                             ratings from every stored game
python afl.py results  |  show <id>  |  export                                   what has been played
python afl.py render <id>                                                        video of a stored game
python afl.py bots  |  check <bot>  |  add <file> --as mine/name                 the bot library
python afl.py app                                                                the web app
python afl.py --game afl18 ...    python afl.py --engine 1 ...                    the 18-a-side game / an older engine
```

`python afl.py <command> --help` explains every option.
