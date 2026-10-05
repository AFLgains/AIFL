"""Controller interface (anything that turns a full game state into a team's actions) and SafeBot, which every bot
loaded from the library is wrapped in. Game-agnostic: the actions are whatever the game's own Action type is."""
from __future__ import annotations


class TeamController:
    name = "base"

    def __init__(self, team: str):
        self.team = team            # "A" or "B"

    def choose_actions(self, game_state: dict, problems: list[str]) -> tuple[str, list]:
        """Return (intent, actions). `problems` lists the invalid actions from the previous turn."""
        raise NotImplementedError

    def team_ids(self, state):
        return [p["id"] for p in state["team_" + self.team]]

    def opponent_ids(self, state):
        return [p["id"] for p in state["team_" + ("B" if self.team == "A" else "A")]]


class SafeBot(TeamController):
    """Wraps a bot: an exception becomes a no-op turn and is counted, so one broken bot never crashes a tournament.
    `spec` is the bot's library spec and `bot_hash` the fingerprint of its code; both reach the results store."""

    def __init__(self, inner, spec, bot_hash=None):
        super().__init__(inner.team); self.inner = inner; self.spec = spec; self.bot_hash = bot_hash
        self.name = spec; self.errors = []

    def choose_actions(self, state, problems):
        try:
            intent, acts = self.inner.choose_actions(state, problems)
            return intent, list(acts)
        except Exception as e:                                             # noqa: BLE001
            if len(self.errors) < 20:
                self.errors.append("t=%.1f %s: %s" % (state.get("time", -1), type(e).__name__, str(e)[:200]))
            return "error", []

    def observe_game(self, game):                                          # a searching bot gets the true game each decision
        hook = getattr(self.inner, "observe_game", None)
        if hook is not None:
            hook(game)

    @property
    def last_problems(self):
        return getattr(self.inner, "last_problems", [])

    @property
    def last_info(self):                                                   # a searching or LLM bot's per-decision stats reach the log
        return getattr(self.inner, "last_info", {})

    @property
    def last_detail(self):
        return getattr(self.inner, "last_detail", None)

    @property
    def last_prediction(self):
        return getattr(self.inner, "last_prediction", "")
