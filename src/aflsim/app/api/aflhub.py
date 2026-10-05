"""Decision-state JSONL for the Replay Room renderer.

Stored match logs contain the original orders and dense position frames, but not full
observations at decision times. Replaying those orders against the recorded seed
reconstructs the exact state the NBAi viewer expects, including velocities, flight
and recent events. This works even when the original controllers are no longer available.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from aflsim.app import services as S

router = APIRouter(prefix="/api/aflhub", tags=["aflhub"])


@router.get("/matches/{match_id}/jsonl")
def match_jsonl(match_id: int):
    from aflsim.engine import run_match
    from aflsim.games import get_game
    from aflsim.match.store import Store
    from aflsim.video.render import ReplayOrders, game_log

    game = S.game()
    st = Store(game)
    try:
        row = st.match(match_id)
    finally:
        st.close()
    if row is None:
        raise HTTPException(404, "no match %d" % match_id)
    try:
        ep = game_log(row, game)
        g = get_game(game)
        rules = g.Rules.from_log(ep["meta"]["rules"])
        header = {"kind": "header", "match_id": match_id, "game": game, "engine_version": row["engine_version"],
                  "team_A": row["bot_a"], "team_B": row["bot_b"], "seed": ep["meta"]["seed"],
                  "seconds": row["seconds"], "final_score": {"A": row["score_a"], "B": row["score_b"]},
                  "rules": ep["meta"]["rules"]}
        lines = [json.dumps(header)]

        def capture(game_obj, state):
            lines.append(json.dumps({"kind": "decision", "k": len(lines) - 1, "t": round(game_obj.t, 2),
                                     "trigger": state["decision_reason"], "state": state}))

        new = run_match(g, ReplayOrders("A", ep["decisions"], g), ReplayOrders("B", ep["decisions"], g), rules,
                        ep["meta"]["seed"], max_decisions=row["max_decisions"], record="none", on_state=capture)
        if (new["stats"]["score_A"], new["stats"]["score_B"]) != (row["score_a"], row["score_b"]) or len(new["decisions"]) != len(ep["decisions"]):
            raise RuntimeError("the recorded match diverged during replay")
    except (RuntimeError, KeyError, ValueError, IndexError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response("\n".join(lines) + "\n", media_type="application/x-ndjson")
