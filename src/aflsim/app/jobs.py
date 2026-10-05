"""Jobs: every ACTION the app takes (a match, a tournament, a render, a bot check, a rating) is
a separate process running the same `afl.py` command a person would type. That keeps the UI honest (it can do nothing
the CLI can't), keeps a crash or a long tournament out of the web server, and gives every action a log.

Each job is persisted under results/jobs/: <id>.json (what, when, status, outputs) and <id>.log (everything it
printed), so the job list survives a restart of the app. Commands are built from validated parameters by the API
(never from raw text), run without a shell, and bound to this machine.

Rules carried over from the project: only one job that plays an LLM bot runs at a time (they cost money).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import signal
import subprocess
import sys
import threading
import uuid

from aflsim import paths

AFL_PY = os.path.join(paths.repo(), "afl.py")
MATCH_ROW = re.compile(r"^#(\d+)\s")
VIDEO_LINE = re.compile(r"^(?:video: )?(\S.*\.(?:mp4|png))\s*$")


def _now():
    return _dt.datetime.now().isoformat(timespec="seconds")


def jobs_dir() -> str:
    d = os.path.join(paths.home(), "results", "jobs")
    os.makedirs(d, exist_ok=True)
    return d


def _alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class JobManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.procs = {}                                                     # id -> Popen (jobs started by this process)
        for j in self.list():                                               # jobs left "running" by a previous app instance
            if j["status"] == "running" and not _alive(j.get("pid")):
                j["status"] = "lost"; j["finished"] = j.get("finished") or _now(); self._save(j)

    # ---- storage
    def _path(self, jid, ext):
        return os.path.join(jobs_dir(), "%s.%s" % (jid, ext))

    def _save(self, j):
        with open(self._path(j["id"], "json"), "w", encoding="utf-8") as f:
            json.dump(j, f, indent=1)

    def get(self, jid) -> dict | None:
        p = self._path(jid, "json")
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None

    def list(self, limit=50) -> list[dict]:
        files = sorted((f for f in os.listdir(jobs_dir()) if f.endswith(".json")), reverse=True)[:limit]
        out = []
        for f in files:
            try:
                out.append(json.load(open(os.path.join(jobs_dir(), f), encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        return sorted(out, key=lambda j: j["created"], reverse=True)

    def log(self, jid, tail_bytes=60_000) -> str:
        p = self._path(jid, "log")
        if not os.path.exists(p):
            return ""
        with open(p, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - tail_bytes))
            return f.read().decode("utf-8", errors="replace")

    # ---- running
    def running_llm(self) -> dict | None:
        return next((j for j in self.list() if j["status"] == "running" and j.get("uses_llm")), None)

    def start(self, kind: str, title: str, argv: list[str], uses_llm=False, meta=None) -> dict:
        with self.lock:
            if uses_llm and self.running_llm():
                raise RuntimeError("an LLM job is already running (%s): one at a time" % self.running_llm()["title"])
            jid = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
            job = {"id": jid, "kind": kind, "title": title, "argv": list(argv), "status": "running", "created": _now(), "started": _now(),
                   "finished": None, "returncode": None, "uses_llm": bool(uses_llm), "meta": meta or {}, "outputs": {"matches": [], "files": []}}
            logf = open(self._path(jid, "log"), "wb")
            env = dict(os.environ); env["PYTHONUNBUFFERED"] = "1"; env["PYTHONIOENCODING"] = "utf-8"
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            proc = subprocess.Popen([sys.executable, AFL_PY] + list(argv), cwd=paths.repo(), stdout=logf, stderr=subprocess.STDOUT, env=env,
                                    creationflags=flags, start_new_session=(os.name != "nt"))
            job["pid"] = proc.pid
            self.procs[jid] = proc
            self._save(job)
        threading.Thread(target=self._watch, args=(jid, proc, logf), daemon=True).start()
        return job

    def _watch(self, jid, proc, logf):
        rc = proc.wait()
        logf.close()
        with self.lock:
            j = self.get(jid)
            if j["status"] == "running":
                j["status"] = "done" if rc == 0 else "failed"
            j["returncode"] = rc; j["finished"] = _now()
            j["outputs"] = self.parse_outputs(self.log(jid, tail_bytes=2_000_000))
            self._save(j); self.procs.pop(jid, None)

    @staticmethod
    def parse_outputs(text: str) -> dict:
        matches = []; files = []
        for line in text.splitlines():
            m = MATCH_ROW.match(line)
            if m:
                matches.append(int(m.group(1)))
            v = VIDEO_LINE.match(line.strip())
            if v and os.path.exists(v.group(1)):
                files.append(v.group(1))
        vroot = os.path.normcase(os.path.abspath(paths.videos_dir("afl8")))
        videos = [os.path.relpath(f, paths.videos_dir("afl8")).replace(os.sep, "/") for f in files
                  if f.endswith(".mp4") and os.path.normcase(os.path.abspath(f)).startswith(vroot + os.sep)]
        return {"matches": sorted(set(matches)), "files": files, "videos": videos}

    def cancel(self, jid) -> dict:
        j = self.get(jid)
        if not j or j["status"] != "running":
            return j
        pid = j.get("pid")
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except OSError:
                pass
        with self.lock:
            j = self.get(jid); j["status"] = "cancelled"; self._save(j)
        return j
