"""One-off import of the old repo's ladder (afl_llm_play/arena/progress.json: 120-second games, every bot v every bot)
into the results store, so today's ratings carry over. Rows are marked source='legacy' and carry no seed or log.

The labels are translated to this repo's specs ('climb_my_bot' -> 'ladder/climb/my_bot'), and each row gets the
bot's CURRENT hash: the ladder bots were copied unchanged, so their old results are theirs.
"""
from __future__ import annotations

import json

from aflsim.games import DEFAULT_GAME, engine_version, get_game


def translate(label: str) -> str:
    if label.startswith("zoo:"):
        return label
    folder, _, stem = label.partition("_")
    return "ladder/%s/%s" % (folder, stem)


def import_progress(path: str, store, seconds: float = 120.0, game: str = DEFAULT_GAME) -> dict:
    from aflsim.bots.registry import bot_hash
    if store.matches(source="legacy", limit=1):
        return {"imported": 0, "skipped": 0, "note": "legacy ladder already imported"}
    g = get_game(game)
    data = json.load(open(path, encoding="utf-8"))
    hashes = {}
    rows = []; skipped = set()
    for m in data["matches"]:
        a, b = translate(m["a"]), translate(m["b"])
        for x in (a, b):
            if x not in hashes:
                try:
                    hashes[x] = bot_hash(x, game)
                except (FileNotFoundError, KeyError):
                    hashes[x] = None
        if hashes[a] is None or hashes[b] is None:
            skipped.update(x for x in (a, b) if hashes[x] is None); continue
        rows.append({"game": game, "engine_version": engine_version(g), "seconds": seconds, "seed": None, "bot_a": a, "bot_b": b,
                     "hash_a": hashes[a], "hash_b": hashes[b], "outcome": float(m["score"]), "result": "full_time", "source": "legacy"})
    store.add_many(rows)
    return {"imported": len(rows), "skipped": len(data["matches"]) - len(rows), "missing_bots": sorted(skipped)}
