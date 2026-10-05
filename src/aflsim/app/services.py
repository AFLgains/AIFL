"""What the app's API is built on: read-only views of the library, the store and the file system (called directly),
and the argv builders that turn validated requests into `afl.py` jobs. Kept apart from the HTTP layer so each piece
can be tested without a server, and so a future section (or a Claude agent tool) reuses the same functions."""
from __future__ import annotations

import glob
import json
import inspect as _inspect
import os
import re
import time
import tomllib

import contextvars

from aflsim import paths
from aflsim.games import DEFAULT_GAME, engine_version, engines, get_game

_APPGAME = contextvars.ContextVar("aflsim_app_game", default=DEFAULT_GAME)   # set per request from the top bar (server.py)
NAME_RE = re.compile(r"^[a-z0-9_]+(/[a-z0-9_]+)*$")
EDITABLE_ROOTS = ("community", "drafts")                                   # new code bots go here; the ladder is history
LLM_TYPES = {"jev": ["backend", "model", "prompt", "x_step", "y_step", "sample"],
             "llm": ["provider", "temperature", "reasoning_effort", "cache"],
             "coached": ["coach", "player", "pack", "coach_every", "reasoning_effort", "cache"]}
_CACHE = {}


# ------------------------------------------------------------------ context: which game, which engine version
def game() -> str:
    return _APPGAME.get()


def engine() -> int:
    return engine_version(get_game(game()))


def games() -> list[str]:
    import pkgutil
    import aflsim.games as G
    return sorted((m.name for m in pkgutil.iter_modules(G.__path__) if m.ispkg), key=lambda n: (n != DEFAULT_GAME, len(n), n))


def contexts() -> list[dict]:
    """What the top bar can switch between: every game, at every engine version it can play."""
    out = []
    for name in games():
        g = get_game(name)
        for v in engines(g):
            out.append({"id": "%s.%d" % (name, v), "game": name, "engine": v, "current": v == g.ENGINE_VERSION,
                        "label": "%s · engine v%d" % (name.upper(), v)})
    return out


def parse_context(text: str | None):
    """'afl8.1' -> ('afl8', 1); None for anything that isn't a context we have."""
    for c in contexts():
        if c["id"] == (text or "").strip():
            return c["game"], c["engine"]
    return None


def have(module: str) -> bool:
    """Is this part of the platform in this copy? (The public repository ships the engine, the app and the bot
    templates; the analysis board, the Lab, the value model and the LLM bots are private.)"""
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def features() -> dict:
    """What this game supports in the app: the value model drives the board's values, the sandbox and the Lab."""
    g = get_game(game())
    try:
        g.encoder(); value = True
    except (NotImplementedError, ImportError):                              # no value model in this copy
        value = False
    board = have("aflsim.app.api.analysis") and have("aflsim.analysis.timeline")
    return {"value_model": value, "analysis": board, "sandbox": value and board, "lab": value and game() == DEFAULT_GAME and have("aflsim.app.api.lab"),
            "board_setup": value and board, "llm": have("aflsim.games.afl8.llm_bots")}


def ctx_argv(argv: list) -> list:
    """A job runs in the context it was started from."""
    return ["--game", game(), "--engine", str(engine())] + list(argv)


def ctx_title(title: str) -> str:
    return "[%s v%d] %s" % (game(), engine(), title)


def _cached(key, ttl, fn):
    key = (key, game(), engine())
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn(); _CACHE[key] = (time.time(), val)
    return val


def invalidate():
    _CACHE.clear()


# ------------------------------------------------------------------ bots
def bot_group(spec: str) -> str:
    if spec.startswith("zoo:"):
        return "zoo"
    if spec.startswith("llm:"):
        return "llm"
    return spec.split("/")[0] if "/" in spec else "other"


def ladders():
    """{seconds: ratings} for the ladders that exist (120 s legacy, 240 s ...), cached briefly (they fit every game)."""
    def build():
        from aflsim.match.ladder import ladder
        from aflsim.match.store import Store
        st = Store(game()); out = {}
        for s in sorted({r[0] for r in st.db.execute("SELECT DISTINCT seconds FROM matches")}):
            ratings, games, n = ladder(st, s, game=game())
            if n:
                out[s] = {"ratings": ratings, "games": games, "n": n}
        st.close()
        return out
    return _cached("ladders", 30, build)


def list_bots() -> list[dict]:
    from aflsim.bots.registry import library
    lad = ladders(); out = []
    for spec in library(game()):
        row = {"spec": spec, "group": bot_group(spec), "kind": "llm" if spec.startswith("llm:") else ("zoo" if spec.startswith("zoo:") else "code"),
               "editable": is_editable(spec)}
        for s, L in lad.items():
            if spec in L["ratings"]:
                row["rating_%d" % int(s)] = round(L["ratings"][spec]); row["games_%d" % int(s)] = L["games"].get(spec, 0)
        out.append(row)
    return out


def is_editable(spec: str) -> bool:
    return spec.startswith("llm:") or spec.split("/")[0] in EDITABLE_ROOTS


def bot_source(spec: str) -> dict:
    from aflsim.bots.registry import bot_hash, code_path, llm_config_path
    if spec.startswith("zoo:"):
        cls = get_game(game()).ZOO[spec[4:]]
        return {"spec": spec, "kind": "zoo", "path": _inspect.getsourcefile(cls), "text": _inspect.getsource(cls), "editable": False, "hash": bot_hash(spec, game())}
    if spec.startswith("llm:"):
        p = llm_config_path(spec, game())
        return {"spec": spec, "kind": "llm", "path": p, "text": open(p, encoding="utf-8").read(), "editable": True, "hash": bot_hash(spec, game())}
    p = code_path(spec, game())
    return {"spec": spec, "kind": "code", "path": p, "text": open(p, encoding="utf-8").read(), "editable": is_editable(spec), "hash": bot_hash(spec, game())}


def code_template() -> str:
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bots", "botkit_template", "my_bot.py")
    return open(p, encoding="utf-8").read()


def save_code_bot(name: str, text: str, overwrite=False) -> str:
    """Write bots/<game>/code/<name>.py. Only under community/ or drafts/ (the rest of the library is
    history: copy a bot to drafts/ to change it). Returns the spec."""
    if not NAME_RE.match(name) or name.split("/")[0] not in EDITABLE_ROOTS or "/" not in name:
        raise ValueError("name must look like community/my_bot or drafts/my_bot (lower case, digits, _)")
    compile(text, name, "exec")                                            # a syntax error is refused before it reaches the library
    p = os.path.join(paths.bots_dir(game()), "code", *name.split("/")) + ".py"
    if os.path.exists(p) and not overwrite:
        raise FileExistsError("%s exists" % name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    invalidate()
    return name


def llm_toml(cfg: dict) -> str:
    t = cfg.get("type")
    if t not in LLM_TYPES:
        raise ValueError("type must be one of %s" % ", ".join(LLM_TYPES))
    lines = ["# %s" % (cfg.get("comment") or "an instruction bot made in the app").replace("\n", " "), 'type = "%s"' % t]
    for k in LLM_TYPES[t]:
        v = cfg.get(k)
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            lines.append("%s = %s" % (k, "true" if v else "false"))
        elif isinstance(v, (int, float)):
            lines.append("%s = %s" % (k, v))
        else:
            lines.append('%s = "%s"' % (k, str(v).replace('"', "'")))
    text = "\n".join(lines) + "\n"
    tomllib.loads(text)
    return text


def save_llm_bot(name: str, cfg: dict, overwrite=False) -> str:
    if not re.match(r"^[a-z0-9_]+$", name):
        raise ValueError("name: lower case letters, digits and _ only")
    p = os.path.join(paths.bots_dir(game()), "llm", name + ".toml")
    if os.path.exists(p) and not overwrite:
        raise FileExistsError("llm:%s exists" % name)
    text = llm_toml(cfg)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    invalidate()
    return "llm:" + name


# ------------------------------------------------------------------ results
def store():
    from aflsim.match.store import Store
    return Store(game())


SCOPES = {
    "all": "every game except imported history",
    "single": "games played on their own (not in a tournament)",
    "tournament": "games played in tournaments",
    "legacy": "imported history from the old repo",
    "everything": "every game, imported history included",
}


def video_ids() -> dict:
    """match id -> its rendered videos (relative paths), from the file names in videos/<game>/ (not the archive)."""
    root = paths.videos_dir(game()); out = {}
    for p in glob.glob(os.path.join(root, "*.mp4")):
        m = re.match(r"^(\d+)(?:_|\.mp4)", os.path.basename(p))
        if m:
            out.setdefault(int(m.group(1)), []).append(os.path.basename(p))
    return out


def matches(bot=None, tournament=None, scope="all", seconds=None, has_video=False, limit=200, offset=0, engine_version=None) -> dict:
    """One page of results, newest first, with each row's tournament name and whether it has a video. Also returns
    the total matching and a sentence saying what is shown, so the page can say exactly what the list is."""
    if scope not in SCOPES:
        raise ValueError("scope must be one of %s" % ", ".join(SCOPES))
    q = ["1=1"]; args = []
    if tournament:
        scope = "tournament"; q.append("m.tournament_id=?"); args.append(int(tournament))
    elif scope == "tournament":
        q.append("m.tournament_id IS NOT NULL")
    if scope == "single":
        q.append("m.tournament_id IS NULL AND (m.source IS NULL OR m.source NOT LIKE 'legacy%')")
    elif scope == "legacy":
        q.append("m.source LIKE 'legacy%'")
    elif scope in ("all", "tournament"):
        q.append("(m.source IS NULL OR m.source NOT LIKE 'legacy%')")
    if bot:
        q.append("(m.bot_a=? OR m.bot_b=?)"); args += [bot, bot]
    if seconds:
        q.append("abs(m.seconds-?)<1e-6"); args.append(float(seconds))
    engine_version = int(engine_version or engine())
    q.append("m.engine_version=?"); args.append(engine_version)
    vids = video_ids()
    if has_video:
        if not vids:
            return {"rows": [], "total": 0, "describe": "no game has a video yet"}
        q.append("m.id IN (%s)" % ",".join(str(i) for i in vids))
    where = " AND ".join(q)
    st = store()
    total = st.db.execute("SELECT count(*) FROM matches m WHERE %s" % where, args).fetchone()[0]
    cur = st.db.execute("SELECT m.id, m.created, m.seconds, m.seed, m.bot_a, m.bot_b, m.score_a, m.score_b, m.outcome, m.result, m.tournament_id, m.engine_version, "
                        "m.source, m.log_path, t.name AS tournament FROM matches m LEFT JOIN tournaments t ON t.id = m.tournament_id "
                        "WHERE %s ORDER BY m.id DESC LIMIT ? OFFSET ?" % where, args + [int(limit), int(offset)])
    rows = [dict(r) for r in cur]
    tname = None
    if tournament:
        t = st.tournament_by_id(int(tournament)); tname = t["name"] if t else "#%s" % tournament
    st.close()
    for r in rows:
        r["videos"] = vids.get(r["id"], [])
    what = ["games of tournament %s" % tname] if tournament else [SCOPES[scope]]
    if bot:
        what.append("involving %s" % bot)
    if seconds:
        what.append("of %g-second length" % float(seconds))
    what.append("played on engine v%d" % engine_version)
    if has_video:
        what.append("that have a video")
    return {"rows": rows, "total": total, "describe": ", ".join(what)}


def filter_options() -> dict:
    """What the results filters can offer: tournaments, the bots that have played, and game lengths."""
    st = store(); ev = engine()
    bots = [{"bot": r[0], "games": r[1]} for r in st.db.execute(
        "SELECT b, count(*) FROM (SELECT bot_a AS b FROM matches WHERE engine_version=? UNION ALL SELECT bot_b FROM matches WHERE engine_version=?) GROUP BY b ORDER BY b", (ev, ev))]
    lengths = [r[0] for r in st.db.execute("SELECT DISTINCT seconds FROM matches WHERE engine_version=? ORDER BY seconds", (ev,))]
    engines_ = [{"version": r[0], "games": r[1]} for r in st.db.execute("SELECT engine_version, count(*) FROM matches GROUP BY engine_version ORDER BY engine_version DESC")]
    tours = [dict(r) for r in st.db.execute("SELECT t.id, t.name, t.status, count(m.id) AS games FROM tournaments t LEFT JOIN matches m ON m.tournament_id = t.id "
                                            "GROUP BY t.id HAVING games = 0 OR max(m.engine_version) = ? ORDER BY t.id DESC", (ev,))]
    st.close()
    return {"bots": bots, "lengths": lengths, "tournaments": tours, "scopes": SCOPES, "engines": engines_, "engine_now": ev}


def match_detail(mid: int) -> dict | None:
    import json
    st = store(); r = st.match(mid)
    if not r:
        st.close(); return None
    t = st.tournament_by_id(r["tournament_id"]) if r.get("tournament_id") else None
    r["tournament"] = t["name"] if t else None
    st.close()
    r["stats"] = json.loads(r.pop("stats_json") or "{}")
    r["videos"] = [os.path.relpath(p, paths.videos_dir(game())).replace(os.sep, "/")
                   for p in sorted(glob.glob(os.path.join(paths.videos_dir(game()), "%d.mp4" % mid)) + glob.glob(os.path.join(paths.videos_dir(game()), "%d_*.mp4" % mid)))]
    r["replayable"] = bool(r["log_path"] and os.path.exists(r["log_path"])) or (r["seed"] is not None and not r["bot_a"].startswith("llm:") and not r["bot_b"].startswith("llm:"))
    return r


def ladder_table(seconds: float) -> dict:
    L = ladders().get(float(seconds))
    if not L:
        return {"seconds": seconds, "n": 0, "rows": []}
    rows = sorted(({"bot": b, "rating": round(r), "games": L["games"].get(b, 0)} for b, r in L["ratings"].items()), key=lambda x: -x["rating"])
    return {"seconds": seconds, "n": L["n"], "rows": rows}


def _tournament_engine(st, tid):
    """The engine a tournament's games were played on (None before its first game)."""
    r = st.db.execute("SELECT max(engine_version) FROM matches WHERE tournament_id=?", (tid,)).fetchone()
    return r[0] if r else None


def tournaments() -> list[dict]:
    """The tournaments of this game played on the engine in force (and any not started yet)."""
    st = store(); ev = engine(); out = []
    for t in st.tournaments():
        if _tournament_engine(st, t["id"]) in (None, ev):
            out.append(dict(t, games=st.db.execute("SELECT count(*) FROM matches WHERE tournament_id=?", (t["id"],)).fetchone()[0]))
    st.close()
    return out


def tournament_detail(tid: int) -> dict:
    from aflsim.match.tournament import tournament_tables
    st = store(); t = tournament_tables(st, tid, game()); st.close()
    return t


def tournament_configs() -> list[dict]:
    out = []
    for p in sorted(glob.glob(os.path.join(paths.tournaments_dir(), "*.toml"))):
        text = open(p, encoding="utf-8").read()
        try:
            cfg = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            cfg = {}
        if cfg.get("game", DEFAULT_GAME) != game():                       # each game's tournaments on its own page
            continue
        out.append({"file": os.path.basename(p), "path": p, "text": text, "name": cfg.get("name"), "format": cfg.get("format"), "seconds": cfg.get("seconds")})
    return out


def save_tournament_config(cfg: dict, overwrite=False) -> str:
    """Build and write tournaments/<name>.toml from the builder's fields."""
    from aflsim.bots.registry import bot_hash
    name = cfg.get("name", "")
    if not re.match(r"^[a-z0-9_]+$", name):
        raise ValueError("name: lower case letters, digits and _ only")
    fmt = cfg.get("format")
    if fmt not in ("round_robin", "groups", "gauntlet", "ladder"):
        raise ValueError("format must be round_robin, groups, gauntlet or ladder")
    q = lambda xs: "[" + ", ".join('"%s"' % x for x in xs) + "]"
    lines = ["# made in the app"] + (['game = "%s"' % game()] if game() != DEFAULT_GAME else []) + ['name = "%s"' % name, 'format = "%s"' % fmt, "seconds = %g" % float(cfg.get("seconds", 240)),
             "seeds = %d" % int(cfg.get("seeds", 5)), "seed = %d" % int(cfg.get("seed", 100000))]
    specs = []
    if fmt in ("round_robin", "ladder"):
        bots = cfg.get("bots")
        if bots == "library":
            lines.append('bots = "library"')
        else:
            if not bots or len(bots) < 2:
                raise ValueError("pick at least two bots")
            specs += bots; lines.append("bots = " + q(bots))
    elif fmt == "gauntlet":
        specs += [cfg["challenger"]] + (cfg.get("field") or [])
        lines += ['challenger = "%s"' % cfg["challenger"], "field = " + q(cfg["field"]) if isinstance(cfg.get("field"), list) else 'field = "library"']
    else:
        groups = cfg.get("groups") or {}
        if len(groups) < 2 or any(len(v) < 2 for v in groups.values()):
            raise ValueError("groups: at least two groups of at least two bots")
        if cfg.get("finals"):
            lines.append("finals = %d" % int(cfg["finals"]))
        lines.append("[groups]")
        for k, v in groups.items():
            if not re.match(r"^[A-Za-z0-9_]+$", k):
                raise ValueError("group names: letters and digits")
            specs += v; lines.append("%s = %s" % (k, q(v)))
    for s in specs:
        if s.startswith("llm:") and not cfg.get("allow_llm"):
            raise ValueError("%s is an LLM bot (it costs money): tick 'allow LLM bots' to include it" % s)
        bot_hash(s, game())                                                   # every bot must exist
    text = "\n".join(lines) + "\n"
    tomllib.loads(text)
    p = os.path.join(paths.tournaments_dir(), name + ".toml")
    if os.path.exists(p) and not overwrite:
        raise FileExistsError("tournaments/%s.toml exists" % name)
    os.makedirs(paths.tournaments_dir(), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return p


# ------------------------------------------------------------------ media
def videos() -> list[dict]:
    root = paths.videos_dir(game()); out = []
    for p in glob.glob(os.path.join(root, "**", "*.mp4"), recursive=True):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        m = re.match(r"^(\d+)(?:_|\.mp4)", rel)
        out.append({"path": rel, "size_mb": round(os.path.getsize(p) / 1e6, 1), "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
                    "match_id": int(m.group(1)) if m else None, "archive": rel.startswith("archive/")})
    return sorted(out, key=lambda v: v["modified"], reverse=True)


def safe_join(root: str, rel: str) -> str:
    p = os.path.abspath(os.path.join(root, rel))
    if not os.path.normcase(p).startswith(os.path.normcase(os.path.abspath(root)) + os.sep):
        raise PermissionError("outside %s" % root)
    return p


# ------------------------------------------------------------------ jobs: validated requests -> afl.py argv
def _spec(s):
    s = (s or "").strip()
    if not s or any(c in s for c in "\n\r\"'`;|&<>"):
        raise ValueError("bad bot spec %r" % s)
    from aflsim.bots.registry import bot_hash
    bot_hash(s, game())                                                       # must exist
    return s


def match_argv(p: dict):
    from aflsim.bots.registry import is_llm
    a, b = _spec(p["bot_a"]), _spec(p["bot_b"])
    argv = ["match", a, b, "--seconds", "%g" % float(p.get("seconds") or 240), "--seed", str(int(p.get("seed") or 1)), "--games", str(max(1, int(p.get("games") or 1)))]
    if p.get("both_ends"):
        argv.append("--both-ends")
    if p.get("video"):
        argv.append("--video")
    if p.get("value_bar"):
        argv.append("--value-bar")
    if p.get("max_decisions"):
        argv += ["--max-decisions", str(int(p["max_decisions"]))]
    argv += ["--parallel", str(max(1, int(p.get("parallel") or 8)))]
    return argv, "%s v %s" % (a, b), is_llm(a) or is_llm(b)


def tournament_argv(p: dict):
    path = safe_join(paths.tournaments_dir(), p["file"])
    if not os.path.exists(path):
        raise FileNotFoundError(p["file"])
    cfg = tomllib.load(open(path, "rb"))
    g_ = cfg.get("game", DEFAULT_GAME)
    if g_ != game():
        raise ValueError("%s is a %s tournament: switch the top bar to %s to run it" % (p["file"], g_, g_))
    st = store(); t = st.tournament(cfg["name"]) if cfg.get("name") else None
    ev = _tournament_engine(st, t["id"]) if t else None; st.close()
    if ev not in (None, engine()):
        raise ValueError("tournament %s was played on engine v%d: switch the top bar to engine v%d to resume it" % (cfg.get("name"), ev, ev))
    from aflsim.match.tournament import plan
    uses_llm = any(b.startswith("llm:") for pairs in plan(cfg, game()).values() for pair in pairs for b in pair)
    argv = ["tournament", path, "--parallel", str(max(1, int(p.get("parallel") or 8))), "-v"]
    if p.get("logs"):
        argv.append("--logs")
    return argv, "tournament %s" % (cfg.get("name") or p["file"]), uses_llm


def rate_argv(p: dict):
    from aflsim.bots.registry import is_llm
    b = _spec(p["bot"])
    return (["rate", b, "--seconds", "%g" % float(p.get("seconds") or 240), "--games", str(int(p.get("games") or 10)), "--panel", str(int(p.get("panel") or 16)),
             "--parallel", str(max(1, int(p.get("parallel") or 8)))], "rate %s" % b, is_llm(b))


def render_argv(p: dict):
    argv = ["render", str(int(p["match_id"])), "--speed", "%g" % float(p.get("speed") or 2)]
    if p.get("value_bar"):
        argv.append("--value-bar")
    if p.get("t0") not in (None, ""):
        argv += ["--from", "%g" % float(p["t0"])]
    if p.get("t1") not in (None, ""):
        argv += ["--to", "%g" % float(p["t1"])]
    return argv, "render match %d%s" % (int(p["match_id"]), " (value bar)" if p.get("value_bar") else ""), False


def check_argv(p: dict):
    b = _spec(p["bot"])
    from aflsim.bots.registry import is_llm
    return ["check", b], "check %s" % b, is_llm(b)


def newladder_argv(p: dict):
    return (["newladder", "--seconds", "%g" % float(p.get("seconds") or 240), "--target", "%g" % float(p.get("target") or 40),
             "--parallel", str(max(1, int(p.get("parallel") or 8)))], "new ladder (adaptive, every code bot)", False)


JOB_KINDS = {"match": match_argv, "tournament": tournament_argv, "rate": rate_argv, "render": render_argv, "check": check_argv, "newladder": newladder_argv}

try:                                                                        # the private parts of the platform, when this copy has them
    import importlib as _il
    _lab = _il.import_module("aflsim.app.lab_services")
except ModuleNotFoundError as _e:
    if not (_e.name or "").startswith("aflsim"):
        raise
    _lab = None
if _lab is not None:
    JOB_KINDS.update(_lab.JOB_KINDS)
    for _name in _lab.__all__:
        globals()[_name] = getattr(_lab, _name)
