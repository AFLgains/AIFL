"""The central results store: one SQLite file per game (results/<game>.sqlite).

    matches       every match that counts: who, seed, length, engine version, score, stats, where its log is
    tournaments   each tournament's config and status (so a tournament resumes where it stopped)
    ratings       snapshots of fitted ladders, so a published rating can be traced back to its games

Only the coordinating process writes (tournament workers return results; they never open the database). WAL mode
lets readers (another terminal running `afl results`) look while a tournament writes.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

from aflsim import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TEXT NOT NULL,
    game TEXT NOT NULL,
    engine_version INTEGER NOT NULL,
    seconds REAL NOT NULL,
    seed INTEGER,
    bot_a TEXT NOT NULL, bot_b TEXT NOT NULL,
    hash_a TEXT, hash_b TEXT,
    score_a INTEGER, score_b INTEGER,
    outcome REAL,                       -- for bot_a: 1 win, 0.5 draw, 0 loss
    result TEXT,
    errors_a INTEGER DEFAULT 0, errors_b INTEGER DEFAULT 0,
    decisions INTEGER, tokens INTEGER DEFAULT 0, wall_s REAL,
    max_decisions INTEGER,
    stats_json TEXT,
    tournament_id INTEGER,
    log_path TEXT,
    source TEXT DEFAULT 'play',         -- play | legacy
    numpy_version TEXT
);
CREATE INDEX IF NOT EXISTS ix_matches_bots ON matches(bot_a, bot_b);
CREATE INDEX IF NOT EXISTS ix_matches_tournament ON matches(tournament_id);
CREATE TABLE IF NOT EXISTS tournaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created TEXT NOT NULL,
    config_toml TEXT,
    status TEXT DEFAULT 'running',
    finished TEXT
);
CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TEXT NOT NULL,
    label TEXT,
    seconds REAL, engine_version INTEGER,
    n_matches INTEGER,
    ratings_json TEXT
);
"""

COLUMNS = ("created", "game", "engine_version", "seconds", "seed", "bot_a", "bot_b", "hash_a", "hash_b", "score_a", "score_b", "outcome", "result",
           "errors_a", "errors_b", "decisions", "tokens", "wall_s", "max_decisions", "stats_json", "tournament_id", "log_path", "source", "numpy_version")


def now():
    return _dt.datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, game: str = "afl8", path: str | None = None):
        self.game = game; self.path = path or paths.results_db(game)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---- matches
    def add_match(self, row: dict) -> int:
        r = {k: row.get(k) for k in COLUMNS}
        r["created"] = r["created"] or now(); r["game"] = r["game"] or self.game
        if isinstance(r["stats_json"], dict):
            r["stats_json"] = json.dumps(r["stats_json"])
        cur = self.db.execute("INSERT INTO matches (%s) VALUES (%s)" % (",".join(COLUMNS), ",".join("?" * len(COLUMNS))), [r[k] for k in COLUMNS])
        self.db.commit()
        return cur.lastrowid

    def add_many(self, rows: list[dict]):
        for row in rows:
            r = {k: row.get(k) for k in COLUMNS}
            r["created"] = r["created"] or now(); r["game"] = r["game"] or self.game
            self.db.execute("INSERT INTO matches (%s) VALUES (%s)" % (",".join(COLUMNS), ",".join("?" * len(COLUMNS))), [r[k] for k in COLUMNS])
        self.db.commit()

    def set_log(self, match_id: int, log_path: str):
        self.db.execute("UPDATE matches SET log_path=? WHERE id=?", (log_path, match_id)); self.db.commit()

    def match(self, match_id: int) -> dict | None:
        r = self.db.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        return dict(r) if r else None

    def matches(self, bot: str | None = None, tournament_id: int | None = None, seconds: float | None = None, engine_version: int | None = None,
                since: str | None = None, source: str | None = None, limit: int | None = None, newest_first=False) -> list[dict]:
        q = "SELECT * FROM matches WHERE 1=1"; args = []
        if bot:
            q += " AND (bot_a=? OR bot_b=?)"; args += [bot, bot]
        if tournament_id is not None:
            q += " AND tournament_id=?"; args.append(tournament_id)
        if seconds is not None:
            q += " AND abs(seconds-?)<1e-6"; args.append(seconds)
        if engine_version is not None:
            q += " AND engine_version=?"; args.append(engine_version)
        if since:
            q += " AND created>=?"; args.append(since)
        if source:
            q += " AND source=?"; args.append(source)
        q += " ORDER BY id %s" % ("DESC" if newest_first else "ASC")
        if limit:
            q += " LIMIT %d" % int(limit)
        return [dict(r) for r in self.db.execute(q, args)]

    def count(self) -> int:
        return self.db.execute("SELECT count(*) FROM matches").fetchone()[0]

    # ---- tournaments
    def tournament(self, name: str) -> dict | None:
        r = self.db.execute("SELECT * FROM tournaments WHERE name=?", (name,)).fetchone()
        return dict(r) if r else None

    def tournament_by_id(self, tid: int) -> dict | None:
        r = self.db.execute("SELECT * FROM tournaments WHERE id=?", (tid,)).fetchone()
        return dict(r) if r else None

    def tournaments(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM tournaments ORDER BY id")]

    def start_tournament(self, name: str, config_toml: str) -> int:
        t = self.tournament(name)
        if t:
            return t["id"]
        cur = self.db.execute("INSERT INTO tournaments (name, created, config_toml) VALUES (?,?,?)", (name, now(), config_toml))
        self.db.commit()
        return cur.lastrowid

    def finish_tournament(self, tid: int, status="finished"):
        self.db.execute("UPDATE tournaments SET status=?, finished=? WHERE id=?", (status, now(), tid)); self.db.commit()

    def played_keys(self, tid: int) -> set:
        """(bot_a, bot_b, seed) already played in a tournament: those jobs are skipped on resume."""
        return {(r[0], r[1], r[2]) for r in self.db.execute("SELECT bot_a, bot_b, seed FROM matches WHERE tournament_id=?", (tid,))}

    # ---- rating snapshots
    def save_ratings(self, label: str, seconds: float, engine_version: int, n_matches: int, ratings: dict) -> int:
        cur = self.db.execute("INSERT INTO ratings (created, label, seconds, engine_version, n_matches, ratings_json) VALUES (?,?,?,?,?,?)",
                              (now(), label, seconds, engine_version, n_matches, json.dumps(ratings)))
        self.db.commit()
        return cur.lastrowid
