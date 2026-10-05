"""My bot: a (very simple) starting point. Rename the label, and write your team's decisions in choose_actions.

The state is described in README.md (player ids A1-A8 / B1-B8: A1-A2 midfielders, A3-A5 defenders, A6-A8 forwards,
and the same for B). Test it with:  python check_bot.py my_bot.py
Return one Action per player you want to instruct; a player you leave out carries on with its previous order.

Actions (see the kit README for the full description):
    Action(pid, "MOVE", target=[x, y], pace="sprint" | "run" | "jog")
    Action(pid, "HOLD")
    Action(pid, "KICK", target=[x, y], power=0.1..1.0)
    Action(pid, "HANDBALL", target=[x, y], power=...)  or  Action(pid, "HANDBALL", target_player="A3", power=...)
    Action(pid, "ATTEMPT_POSSESSION")      # go to the ball (or where it lands) and contest it
    Action(pid, "ATTEMPT_MARK")            # contest a kick in flight in the air
    Action(pid, "SPOIL")                   # punch a kick in flight away
    Action(pid, "TACKLE", opponent="B2")
"""
from bot_base import Action, BotBase


class Bot(BotBase):
    def __init__(self, team, rules, seed=0):
        super().__init__(team, rules, seed)
        self.name = "my_bot"

    def choose_actions(self, state, problems):
        mine, theirs, ball, holder = self.split(state)
        acts = []
        for p in mine:
            pid = p["id"]
            if holder == pid:                                              # I have the ball: kick it towards goal
                acts.append(Action(pid, "KICK", target=[self.goal_x, 0.0], power=1.0))
            elif holder is None:                                           # loose: everyone goes for it
                acts.append(Action(pid, "ATTEMPT_POSSESSION"))
            else:                                                          # otherwise hold a spot 20 m ahead of the ball in my lane
                lane = {"midfielder": 0.0, "defender": -20.0, "forward": 20.0}[p["role"]]
                acts.append(Action(pid, "MOVE", target=self.clip(self.ahead(ball["position"][0], 20.0), lane), pace="run"))
        return "my_bot", acts
