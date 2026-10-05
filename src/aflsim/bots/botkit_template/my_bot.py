"""My bot: a starting point. Rename the class's label, then change what you like.

This subclasses RulesController, a complete team: man-marking defenders, leading forwards, midfielders that attack
the ball, a carrier that shoots inside range, kicks to a lead in space, handballs out of trouble or kicks long.
Override any of its methods; the base implementation is in aflsim/games/afl8/controllers/rules_ai.py.
"""
from aflsim.games.afl8.actions import Action
from aflsim.games.afl8.controllers.rules_ai import RulesController


class Bot(RulesController):
    def __init__(self, team, rules, seed):
        super().__init__(team, rules, seed, aggression=0.5)              # aggression 0..1 sets the base shooting range (36-52 m)
        self.name = "my_bot"

    # ------------------------------------------------------------------ the carrier
    def _dispose(self, me, mine, theirs, set_play):
        """me: my player dict; mine / theirs: the two teams' player dicts; set_play: True when I am taking a mark or free."""
        pos = me["pos"]
        d_goal = self.to_goal(pos)                                       # metres to the centre of the goal I attack
        if d_goal <= 30.0 and abs(pos[1]) < 20.0:                        # example: shoot from closer in than the base team does
            return Action(me["id"], "KICK", target=[self.goal_x, 0.0], power=min(1.0, d_goal / self.kick_range(me) + 0.15))
        return super()._dispose(me, mine, theirs, set_play)              # otherwise the base team's choice

    # ------------------------------------------------------------------ off the ball
    def _forward(self, p, lane_y, bpos, we_have, they_have, holder, by_id, their_def):
        """p: this forward; lane_y: its lane; bpos: ball position; who has the ball; by_id: every player by id."""
        if they_have:                                                    # example: rest while the opposition has it, far from me
            if self.dist(p["pos"], bpos) > 40.0:
                return Action(p["id"], "MOVE", target=self.clip(self.ahead(bpos[0], 25.0), lane_y), pace="jog")
        return super()._forward(p, lane_y, bpos, we_have, they_have, holder, by_id, their_def)
