# Research blog

A static page: `index.html`, `css/`, `js/` and the figure data in `assets/`. There is no build step.

```bash
python -m http.server 8772 --directory blog
```

The scripts in `scripts/` regenerate `assets/` from a private checkout that holds the games and the network. They use
`C:\projects\afl_sim` unless `AFL_SIM_HOME` says otherwise.

| Script | Writes | Figures |
|---|---|---|
| `gen_match.py` | `match.json`, `moments.json` | 1, 3, 5, 6, 9, 12 |
| `gen_field.py` | `field.json` | 7, 8 |
| `gen_ladder.py` | `ladder.json` | 4 |
| `gen_results.py` | `results.json`, `reports/` | 13, Tables 1 to 3 (and the copies of the analysts' reports and plans) |
| `space_from_analyst.py` | `space.json` | 14 |
| `gen_sharks_games.py` | `sharks_before.json`, `sharks_after.json` | 15 |

Figures 2, 10 and 11 need no data file. `space_from_analyst.py` runs the Sharks analyst's own figure code on its own data files. Run it inside the sandbox image, with the workspace mounted read-only and no network:

```bash
docker run --rm --network none --read-only --tmpfs /tmp -v <v2_sharks_open workspace>:/ws:ro -v blog/scripts:/sp:ro afl-analyst:v2 python /sp/space_from_analyst.py > blog/assets/space.json
```
 After the network is retrained, change `value_pos` to the new model in
`gen_match.py` and `gen_field.py`, and rerun both.
