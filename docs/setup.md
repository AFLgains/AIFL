# Setting up

## What you need

- **Python 3.11 or newer.** 3.13 is what it's developed on. That's the only thing you install yourself.
- **Nothing else.** In particular:
  - **SQLite** — the results database — is part of Python's standard library (`sqlite3`). There is no server to
    install or run; the database is a single file the platform creates the first time it stores a game.
  - **ffmpeg** — used to encode videos — comes with the `imageio-ffmpeg` Python package, installed with the app
    (below). If you install without the app, videos fall back to an `ffmpeg` on your PATH.
  - No GPU, no Docker, no accounts, no API keys.

## Install

From the repository folder:

```bash
python -m venv .venv                       # a private Python for this project
.venv/bin/pip install -e ".[app]"          # Windows: .venv\Scripts\pip install -e ".[app]"
```

(On Windows, if `python` isn't found, use the launcher: `py -3.13 -m venv .venv`.)

What that installs:

| Group | Packages | For |
|---|---|---|
| always | `numpy`, `matplotlib`, `pillow` | the engine, the replay renderer |
| `[app]` | `fastapi`, `uvicorn`, `imageio-ffmpeg` | the web app, and an ffmpeg for videos |
| `[dev]` | `pytest`, `httpx` | running tests (`pip install -e ".[dev]"`) |

`-e` installs it "editable": the code runs from this folder, so changes you make take effect immediately.

Check it works:

```bash
.venv/bin/python afl.py match zoo:rules zoo:zone
```

You should see one line with the score. Add `--video` to also write `videos/afl8/<match id>.mp4`.

## Running the app

```bash
.venv/bin/python afl.py app                # then open http://127.0.0.1:8765
```

On Windows you can double-click **`run_app.bat`** instead: it starts the app (restarting any copy already running
on the port) and opens the browser. Close its window to stop it. Another port: `python afl.py app --port 8766`
(or `run_app.bat 8766`).

The app is bound to `127.0.0.1` — your own machine only. It can run code (bots) and write files, so it is not
meant to be exposed on a network.

## Where things are stored

Everything the platform writes goes inside the repository folder (or `AFL_HOME`, below):

| Path | What |
|---|---|
| `bots/<game>/code/**/*.py` | **your bot library.** `bots/afl8/code/mine/my_bot.py` is the bot `mine/my_bot`. |
| `results/<game>.sqlite` | the results database (SQLite): every stored match, tournament and rating snapshot |
| `results/logs/<game>/YYYY-MM/<id>.json.gz` | full game logs (every position, ten times a second, and every event) |
| `videos/<game>/` | rendered videos |
| `tournaments/*.toml` | tournament configs |
| `results/jobs/` | the app's job records and logs |

`<game>` is `afl8` or `afl18`. All of these are ignored by git (see `.gitignore`), so your bots and results stay
on your machine unless you choose to commit them.

To look inside the database, any SQLite tool works, e.g. `sqlite3 results/afl8.sqlite "select * from matches limit 5"`,
or use `python afl.py results` / `show <id>` / `export` (CSV).

## Settings (environment variables)

| Variable | Effect |
|---|---|
| `AFL_HOME` | put `results/` and `videos/` somewhere else (e.g. a bigger disk) |
| `AFL_BOTS` | use a bot library folder somewhere else |
| `AFL_TOURNAMENTS` | use a tournament config folder somewhere else |

## Games and engine versions

- `--game afl8` (the default) or `--game afl18` chooses the game, on any command:
  `python afl.py --game afl18 match zoo:rules zoo:press`.
- AFL8 keeps its older engine **v1** playable (players froze when they touched a set play's protected area):
  `python afl.py --engine 1 match ...`. Results are recorded with their engine version, and ratings never mix
  versions.
- In the app, the switch at the top of the page chooses the game and engine for everything you do.

## Tests

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## Troubleshooting

- **"No module named aflsim"** — run commands with the project's Python (`.venv/bin/python`, or
  `.venv\Scripts\python` on Windows), from the repository folder.
- **The app says the port is in use** — another copy is running. Stop it, or use `--port 8766`. (`run_app.bat`
  stops an old copy for you.)
- **Videos fail with "ffmpeg not found"** — install the app extras (`pip install -e ".[app]"`), which bring their
  own ffmpeg, or install ffmpeg and put it on your PATH.
- **The app shows an old version after you changed code** — restart it (Python changes need a restart; the
  browser always loads the current web files).
