"""Actions a controller can issue, and validation of the JSON a controller returns."""
from __future__ import annotations

from dataclasses import dataclass, field

ACTION_TYPES = ("MOVE", "KICK", "HANDBALL", "ATTEMPT_POSSESSION", "ATTEMPT_MARK", "SPOIL", "TACKLE", "HOLD")


@dataclass
class Action:
    player: str
    kind: str
    target: list | None = None          # [x, y] for MOVE / KICK / HANDBALL
    target_player: str | None = None    # HANDBALL to a teammate
    opponent: str | None = None         # TACKLE
    power: float = 1.0                  # KICK / HANDBALL, 0..1
    pace: str = "run"                   # MOVE: sprint | run | jog


def parse_actions(raw, team: str, player_ids: set, opponent_ids: set, rules=None):
    """Validate a controller's {"intent": ..., "actions": [...]} dict. Returns (intent, actions, problems).
    Invalid entries are dropped and described in `problems` (fed back to the controller next turn)."""
    problems, actions = [], []
    if not isinstance(raw, dict):
        return "", [], ["output was not a JSON object"]
    intent = str(raw.get("intent", ""))[:300]
    items = raw.get("actions", [])
    if not isinstance(items, list):
        return intent, [], ["'actions' must be a list"]
    for i, a in enumerate(items):
        if not isinstance(a, dict):
            problems.append("action %d is not an object" % i); continue
        pid = str(a.get("player", "")).upper().strip()
        kind = str(a.get("action", "")).upper().strip()
        if pid not in player_ids:
            problems.append("action %d: '%s' is not one of your players" % (i, pid)); continue
        if kind not in ACTION_TYPES:
            problems.append("action %d (%s): unknown action '%s'" % (i, pid, kind)); continue
        act = Action(pid, kind)
        if kind == "MOVE":
            pace = str(a.get("pace", "run")).lower().strip()
            act.pace = pace if pace in ("sprint", "run", "jog") else "run"
        if kind in ("MOVE", "KICK", "HANDBALL"):
            tgt = a.get("target")
            tp = a.get("target_player")
            if kind == "HANDBALL" and tp is not None:
                tp = str(tp).upper().strip()
                if tp not in player_ids or tp == pid:
                    problems.append("action %d (%s): target_player '%s' is not a teammate" % (i, pid, tp)); continue
                act.target_player = tp
            elif isinstance(tgt, (list, tuple)) and len(tgt) == 2 and all(isinstance(v, (int, float)) for v in tgt):
                act.target = [float(tgt[0]), float(tgt[1])]
            else:
                problems.append("action %d (%s): %s needs target [x, y]%s" % (i, pid, kind, " or target_player" if kind == "HANDBALL" else "")); continue
            if kind in ("KICK", "HANDBALL"):
                try:
                    act.power = float(a.get("power", 1.0))
                except (TypeError, ValueError):
                    act.power = 1.0
                act.power = min(max(act.power, 0.1), 1.0)
        elif kind == "TACKLE":
            opp = str(a.get("opponent", "")).upper().strip()
            if opp not in opponent_ids:
                problems.append("action %d (%s): TACKLE needs an opponent id" % (i, pid)); continue
            act.opponent = opp
        actions.append(act)
    return intent, actions, problems


def action_to_dict(a: Action) -> dict:
    d = {"player": a.player, "action": a.kind}
    if a.kind == "MOVE" and a.pace != "run":
        d["pace"] = a.pace
    if a.target is not None:
        d["target"] = [round(a.target[0], 1), round(a.target[1], 1)]
    if a.target_player:
        d["target_player"] = a.target_player
    if a.opponent:
        d["opponent"] = a.opponent
    if a.kind in ("KICK", "HANDBALL"):
        d["power"] = round(a.power, 2)
    if a.kind == "MOVE" and a.pace != "run":
        d["pace"] = a.pace
    return d
