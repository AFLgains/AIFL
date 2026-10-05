"""A random team, for testing that your bot runs. It is a weak opponent: every player gets a random legal order."""
from bot_base import Action, BotBase


class Bot(BotBase):
    def __init__(self, team, rules, seed=0):
        super().__init__(team, rules, seed)
        self.name = "random"

    def choose_actions(self, state, problems):
        mine, theirs, ball, holder = self.split(state)
        rng = self.rng; L, half = self.r.length, self.r.width / 2
        acts = []
        for p in mine:
            pid = p["id"]; tgt = [float(rng.uniform(0, L)), float(rng.uniform(-half, half))]
            if pid == holder:
                acts.append(Action(pid, "KICK" if rng.random() < 0.6 else "HANDBALL", target=tgt, power=float(rng.uniform(0.3, 1.0))))
            elif rng.random() < 0.5:
                acts.append(Action(pid, "MOVE", target=tgt, pace=str(rng.choice(["sprint", "run", "jog"]))))
            elif rng.random() < 0.6:
                acts.append(Action(pid, str(rng.choice(["ATTEMPT_POSSESSION", "ATTEMPT_MARK", "SPOIL"]))))
            elif holder and holder[0] != self.team:
                acts.append(Action(pid, "TACKLE", opponent=holder))
            else:
                acts.append(Action(pid, "HOLD"))
        return "random", acts
