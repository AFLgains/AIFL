# AFLHub

The replay viewer from `NBAi/frontend`, with its 3D players, stadium, camera controls, animation and audio. Its two JSONL matches and audio clips from `NBAi/AIFL` are bundled in `public/`, so the first match plays without a backend. AIFL stored matches appear in the same library; `GET /api/aflhub/matches/{id}/jsonl` reconstructs decision states from the stored orders and seed for this viewer.

The **Game** tab uses the same 3D field and players for a live match driven by the Python engine. Choose both bot teams and the side to control, then move relative to the camera with WASD/arrows, sprint with Shift, hold and release Space to kick (or tap it to contest without the ball), J to handball, L to spoil, and Q to switch players. Click a teammate to control them directly. Use the top-right Pause button or P to pause and resume the simulation; the controls are listed beside it. Your other players and the opposing team continue playing with their selected bots. A running backend is required for Game.

From the AIFL repository root, `./run_aflhub.sh` starts both the Python backend and Vite frontend, installing missing dependencies on first run. Open http://127.0.0.1:5173/aflhub/ and press Ctrl-C to stop both. To use a different frontend port, run `AFLHUB_PORT=5174 ./run_aflhub.sh` and open port 5174 instead.

From `AIFL/src/aflhub`:

```sh
npm install
npm run dev
```

Open http://127.0.0.1:5173/aflhub/. Start `python afl.py app` in the AIFL root to load stored matches (Vite proxies `/api` to port 8765). Select a match in the library or open `/aflhub/?match=42`. To serve AFLHub from the Python app instead, run `npm run build` and open http://127.0.0.1:8765/aflhub/.

Import another `.jsonl` replay via the file picker. Use Space to play/pause, left/right to seek, the timeline to scrub, and the Broadcast, Aerial, Free and On-ball camera buttons. Click a player to follow them; click the field to clear selection.

## Bundled crowd audio

- `stadium-crowd.wav`: [Arrowhead Stadium crowd noise](https://commons.wikimedia.org/wiki/File:Arrowhead_Stadium_crowd_noise.wav) by Kj1595, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- `applause.wav`: [Applause 2](https://commons.wikimedia.org/wiki/File:277021_sandermotions_applause-2.wav) by Sandermotions, [CC0](https://creativecommons.org/publicdomain/zero/1.0/).
- `referee-whistle.wav`: [Referee whistle blow](https://commons.wikimedia.org/wiki/File:218318_splicesound_referee-whistle-blow-gymnasium.wav) by SpliceSound, [CC0](https://creativecommons.org/publicdomain/zero/1.0/).
