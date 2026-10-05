"""Random and simple-heuristic controllers for either team. The heuristic exists only to exercise the
simulator before spending money on LLM calls: carrier kicks at goal when in range, otherwise to the
teammate nearest the goal; others go to the ball or run goalward; the two nearest opponents of a carrier
tackle. Nothing more."""
from __future__ import annotations

import numpy as np

from ..actions import Action
from aflsim.bots.base import TeamController


class RandomController(TeamController):
    name = "random"

    def __init__(self, team, seed=0):
        super().__init__(team)
        self.rng = np.random.default_rng(seed)

    def choose_actions(self, state, problems):
        rng = self.rng
        L, W = 90.0, 55.0
        holder = state["ball"]["owner"]
        acts = []
        for pid in self.team_ids(state):
            if pid == holder:
                kind = "KICK" if rng.random() < 0.5 else "HANDBALL"
                acts.append(Action(pid, kind, target=[rng.uniform(0, L), rng.uniform(-W / 2, W / 2)], power=rng.uniform(0.3, 1.0)))
            else:
                u = rng.random()
                if u < 0.5:
                    acts.append(Action(pid, "MOVE", target=[rng.uniform(0, L), rng.uniform(-W / 2, W / 2)]))
                elif u < 0.75:
                    acts.append(Action(pid, rng.choice(["ATTEMPT_POSSESSION", "ATTEMPT_MARK", "SPOIL"])))
                elif u < 0.9 and holder is not None and holder[0] != self.team:
                    acts.append(Action(pid, "TACKLE", opponent=holder))
                else:
                    acts.append(Action(pid, "HOLD"))
        return "random", acts


class HeuristicController(TeamController):
    name = "heuristic"

    def choose_actions(self, state, problems):
        goal = np.array([state["goals"]["%s_scores_at_x" % self.team], 0.0])
        mine = state["team_" + self.team]
        holder = state["ball"]["owner"]
        ball = np.array(state["ball"]["position"])
        towards = 1.0 if goal[0] > 45 else -1.0
        acts = []
        for p in mine:
            pos = np.array(p["pos"])
            if p["id"] == holder:
                dist_goal = np.linalg.norm(goal - pos)
                reach = 35 + p["attrs"]["kick_power"] * 30
                if dist_goal <= reach * 0.9:
                    acts.append(Action(p["id"], "KICK", target=[goal[0] + 5.0 * towards, 0.0], power=min(1.0, dist_goal / reach + 0.15)))
                else:
                    mates = [q for q in mine if q["id"] != p["id"]]
                    best = max(mates, key=lambda q: towards * q["pos"][0] - 3 * q["pressure"])
                    tgt = np.array(best["pos"]) + np.array(best["vel"]) * 1.0
                    d = np.linalg.norm(tgt - pos)
                    if d < 12:
                        acts.append(Action(p["id"], "HANDBALL", target_player=best["id"], power=min(1.0, d / 15 + 0.2)))
                    else:
                        acts.append(Action(p["id"], "KICK", target=[float(tgt[0]), float(tgt[1])], power=min(1.0, d / reach + 0.1)))
            elif holder is not None and holder[0] != self.team:
                order = sorted(mine, key=lambda q: np.linalg.norm(np.array(q["pos"]) - ball))
                if p["id"] in [q["id"] for q in order[:2]]:
                    acts.append(Action(p["id"], "TACKLE", opponent=holder))
                else:
                    acts.append(Action(p["id"], "MOVE", target=[float(np.clip(ball[0] - 15 * towards, 2, 88)), float(np.clip(ball[1] * 0.5, -20, 20))]))
            elif state["ball"]["state"] in ("loose", "flight"):
                acts.append(Action(p["id"], "ATTEMPT_MARK" if state["ball"]["state"] == "flight" else "ATTEMPT_POSSESSION"))
            else:
                acts.append(Action(p["id"], "MOVE", target=[float(np.clip(pos[0] + 25.0 * towards, 5, 85)), float(np.clip(pos[1] * 0.8, -20, 20))]))
        return "heuristic", acts
