# The web app

```bash
python afl.py app            # http://127.0.0.1:8765      (Windows: double-click run_app.bat)
```

The switch at the top of the page chooses the **game and engine** — AFL8 engine v2, AFL8 engine v1, AFL18 — and
everything you see and do follows it: the bots, the results, the ladders, new matches and tournaments.

Everything that takes a while (a match series, a tournament, rendering a video) runs as a **job**: the **Jobs**
button (top right) shows what's running, with its live log, and lets you cancel it.

## Develop

The bot library: every bot with its rating, the source of any bot (including the built-in `zoo:` bots, so you can
read how they play), and **New code bot** — write a bot in the browser, starting from the template. It's saved to
`bots/<game>/code/community/` or `drafts/` and checked straight away.

## Play

- **🕹 Play it yourself** — you against a bot, on the keyboard (below).
- **Match** — two bots, a number of seeds, optionally both ends and a video of the first game.
- **Tournaments** — build a config (round robin, groups, gauntlet, ladder), run it, and follow the standings.
- **Rate a bot** — place one bot on the ladder by playing a panel of rated bots.
- **Ladder** — ratings from every stored game of a length.

## Inspect

Every stored game: filter by bot, tournament, length, video. A match page has the score, the statistics, the event
list, its videos, **Render video**, and **👾 Watch** — the game replayed live as a 16-bit broadcast: scoreboard,
coach panels with each team's energy bars, the tilted oval and its pixel crowd, the ball on its arc, the possession
chain, goal celebrations and chiptune sound. **🎬 Make video** in the viewer exports it as an mp4.

**3D replay** on a match page opens AFLHub's replay view: the React/Three.js viewer with camera controls,
scrubbing, crowd audio and JSONL imports. Build it once with `cd src/aflhub && npm install && npm run build`; the app serves it
at `/aflhub/`. For frontend development, `npm run dev` inside that folder runs it at
`http://127.0.0.1:5173/aflhub/` and proxies the API to the app on port 8765.

In AFLHub, the **Game** tab lets you select both bot teams and the side to play, then control one player in a live 3D match. The same stadium, players and ball renderer powers **Replay**; the engine runs the match on the backend. Start both servers with `./run_aflhub.sh`.

## Playing yourself

You're red, attacking right, controlling one player at a time (the yellow **P1** marker); the rest of your team is
run by the bot you pick. It's the real engine with an arcade feel (quicker acceleration, quicker kicks) for both
teams.

| Key | Does |
|---|---|
| Arrows / WASD | run (Shift: sprint — faster, burns energy) |
| Space, with the ball | kick: hold to fill the power meter (the distance), aim with the arrows, let go before the red or it sprays; aim at the goals in range to shoot |
| Space, ball in the air | leap for the mark: a ring closes on where it lands — press when it turns green (too early and you're locked out for a moment) |
| Space, loose ball / their ball | go and gather it / tackle their carrier (get close first) |
| J | handball to the teammate you're pointing at |
| L | spoil (punch it away; the same timing as a mark) |
| Q | switch to the teammate best placed for the ball (dashed circle); hold Q and press an arrow for the teammate that way |
| Esc | quit |

Control also moves by itself: to your ball carrier, to the receiver of your kick, and to a clearly better-placed
teammate when the other team has the ball. After full time, **🎬 Make video** saves your game.
