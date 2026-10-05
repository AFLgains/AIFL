"""One way to name a bot, everywhere: a spec string.

    zoo:ontario                          a built-in rules bot of the game
    mine/my_bot                          bots/<game>/code/mine/my_bot.py  (class Bot)
    community/their_bot                  a bot someone else wrote
    C:/any/where/my_bot.py               any file defining class Bot(team, rules, seed)   (analyst workspaces, drafts)
    llm:jev_v3                           bots/<game>/llm/jev_v3.toml  (an instruction bot: Jev, a coached LLM team...)
    search:<spec>                        look-ahead on top of any bot
    search[h=5,seeds=16,opp=<spec>]:<spec>
    random | idle | noisy:hold:0.4:<spec>   deliberately bad play (value-function data, tests)

Every bot is identified by its canonical spec plus a content fingerprint (`bot_hash`): the hash of its file(s), so
an edited bot never inherits another version's results. Every loaded bot is wrapped in SafeBot.
"""
from __future__ import annotations

import glob
import hashlib
import importlib.util
import os
import sys
import tomllib

from aflsim import paths
from aflsim.bots.base import SafeBot
from aflsim.games import DEFAULT_GAME, get_game

_MODULES = {}                                                               # abs path -> loaded module (loaded once per process)


# ------------------------------------------------------------------ spec parsing
def split_wrapper(spec: str):
    """'search[h=5,opp=zoo:x]:inner' -> ('search', {'h': '5', 'opp': 'zoo:x'}, 'inner'); anything else -> (None, {}, spec)."""
    if spec.startswith("search"):
        rest = spec[len("search"):]
        opts = {}
        if rest.startswith("["):
            end = rest.index("]")
            for part in filter(None, rest[1:end].split(",")):
                k, v = part.split("=", 1)
                opts[k.strip()] = v.strip()
            rest = rest[end + 1:]
        if rest.startswith(":"):
            return "search", opts, rest[1:]
    return None, {}, spec


def _num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in v else f
    except ValueError:
        return v


def _is_path(spec):
    return spec.endswith(".py") or os.path.isabs(spec) or spec.startswith(".")


def code_path(spec: str, game: str = DEFAULT_GAME) -> str:
    """The .py file a code-bot spec refers to (library-relative, or a path)."""
    if _is_path(spec):
        return os.path.abspath(spec)
    return os.path.join(paths.bots_dir(game), "code", *spec.split("/")) + ".py"


def canonical(spec: str, game: str = DEFAULT_GAME) -> str:
    """The name a bot is stored under: library files become library-relative specs, other files absolute paths."""
    kind, opts, inner = split_wrapper(spec)
    if kind == "search":
        o = ",".join("%s=%s" % (k, canonical(v, game) if k in ("autopilot", "opp") else v) for k, v in sorted(opts.items()))
        return "search%s:%s" % ("[%s]" % o if o else "", canonical(inner, game))
    if spec.startswith("noisy:"):
        _, mode, p, inner = spec.split(":", 3)
        return "noisy:%s:%s:%s" % (mode, p, canonical(inner, game))
    if spec.startswith(("zoo:", "llm:", "rl:")) or spec in ("random", "idle"):
        return spec
    if _is_path(spec):
        p = os.path.abspath(spec)
        lib = os.path.join(paths.bots_dir(game), "code")
        if os.path.normcase(p).startswith(os.path.normcase(lib + os.sep)):
            return os.path.relpath(p, lib)[:-3].replace(os.sep, "/")
        return p.replace(os.sep, "/")
    return spec.replace("\\", "/").removesuffix(".py")


def _file_hash(*files):
    h = hashlib.sha256()
    for f in files:
        with open(f, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:16]


def bot_hash(spec: str, game: str = DEFAULT_GAME) -> str:
    """Content fingerprint of a bot. Changes when (and only when) the code or definition that drives it changes."""
    g = get_game(game)
    kind, opts, inner = split_wrapper(spec)
    if kind == "search":
        from aflsim.value.function import resolve_model
        parts = [bot_hash(inner, game), repr(sorted(opts.items())), _file_hash(resolve_model(opts.get("model", "value_pos"), game)),
                 g.source_hash("search.py")] + [bot_hash(opts[k], game) for k in ("autopilot", "opp") if k in opts]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    if spec.startswith("noisy:"):
        return hashlib.sha256(("noisy|" + spec.rsplit(":", 1)[0] + "|" + bot_hash(spec.split(":", 3)[3], game)).encode()).hexdigest()[:16]
    if spec.startswith("zoo:"):
        if spec[4:] not in g.ZOO:
            raise KeyError("no zoo bot %r (have: %s)" % (spec[4:], ", ".join(sorted(g.ZOO))))
        return g.zoo_hash()
    if spec in ("random", "idle"):
        return g.source_hash("testbots.py")
    if spec.startswith("llm:"):
        cfg_path = llm_config_path(spec, game)
        return hashlib.sha256((_file_hash(cfg_path) + "|" + g.source_hash("llm_bots.py", "prompts.py")).encode()).hexdigest()[:16]
    path = code_path(spec, game)
    shared = sorted(glob.glob(os.path.join(os.path.dirname(path), "_*.py")))   # a folder's _files are its bots' shared code
    return _file_hash(path, *shared)


def llm_config_path(spec: str, game: str = DEFAULT_GAME) -> str:
    return os.path.join(paths.bots_dir(game), "llm", spec.split(":", 1)[1] + ".toml")


def is_llm(spec: str) -> bool:
    """Bots that call a paid API: tournaments run their games one at a time."""
    kind, opts, inner = split_wrapper(spec)
    if kind:
        return is_llm(inner) or any(is_llm(opts[k]) for k in ("autopilot", "opp") if k in opts)
    if spec.startswith("noisy:"):
        return is_llm(spec.split(":", 3)[3])
    return spec.startswith("llm:")


# ------------------------------------------------------------------ loading
def load_module(path: str):
    path = os.path.abspath(path)
    if path not in _MODULES:
        if not os.path.exists(path):
            raise FileNotFoundError("no bot file %s" % path)
        name = "aflbot_" + hashlib.sha1(path.encode()).hexdigest()[:10] + "_" + os.path.splitext(os.path.basename(path))[0]
        s = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(s); sys.modules[name] = mod
        s.loader.exec_module(mod)
        _MODULES[path] = mod
    return _MODULES[path]


def _inner(spec, team, rules, seed, game):
    g = get_game(game)
    kind, opts, inner = split_wrapper(spec)
    if kind == "search":
        kw = {k: (v if k in ("model", "autopilot", "opp") else _num(v)) for k, v in opts.items()}
        return g.make_search(inner, kw, team, rules, seed)
    if spec.startswith("zoo:"):
        name = spec[4:]
        if name not in g.ZOO:
            raise KeyError("no zoo bot %r (have: %s)" % (name, ", ".join(sorted(g.ZOO))))
        return g.ZOO[name](team, rules, seed)
    if spec.startswith("llm:"):
        cfg = tomllib.load(open(llm_config_path(spec, game), "rb"))
        return g.build_llm_bot(cfg, team, rules, seed)
    if spec.startswith("rl:"):
        raise NotImplementedError("rl: bots arrive with aflsim.rl (see TODO.md)")
    head, _, arg = spec.partition(":")
    special = g.special_bot(head, arg, team, rules, seed, lambda s, t, r, sd: load_bot(s, t, r, sd, game))
    if special is not None:
        return special
    g.install_compat()
    mod = load_module(code_path(spec, game))
    if not hasattr(mod, "Bot"):
        raise AttributeError("%s defines no class Bot" % code_path(spec, game))
    return mod.Bot(team, rules, seed)


def load_bot(spec: str, team: str, rules, seed: int, game: str = DEFAULT_GAME) -> SafeBot:
    """The bot named by `spec`, playing as `team`, wrapped in SafeBot (carrying its canonical spec and hash)."""
    inner = _inner(spec, team, rules, seed, game)
    return SafeBot(inner, canonical(spec, game), bot_hash(spec, game))


# ------------------------------------------------------------------ the library
def library(game: str = DEFAULT_GAME, include_llm: bool = True) -> list[str]:
    """Every bot the library knows: zoo bots, code bots under bots/<game>/code, and (unless include_llm=False) the
    llm bots under bots/<game>/llm, which cost money to play."""
    g = get_game(game)
    out = ["zoo:" + z for z in sorted(g.ZOO)]
    root = os.path.join(paths.bots_dir(game), "code")
    for f in sorted(glob.glob(os.path.join(root, "**", "*.py"), recursive=True)):
        if os.path.basename(f).startswith("_"):
            continue
        out.append(os.path.relpath(f, root)[:-3].replace(os.sep, "/"))
    if include_llm:
        for f in sorted(glob.glob(os.path.join(paths.bots_dir(game), "llm", "*.toml"))):
            out.append("llm:" + os.path.splitext(os.path.basename(f))[0])
    return out
