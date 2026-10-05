"""The app: a local web front end over the platform.  python afl.py app  (then open http://127.0.0.1:8765)

Layout for growth:
  api/<section>.py   one router per section (develop, play, inspect, lab) plus jobs; a new section is one new file
  services.py        the functions the routers call (reusable without HTTP: tests, scripts, future agent tools)
  jobs.py            every action runs as an `afl.py` process with a persisted log
  web/               the browser side: plain ES modules, no build step; web/js/sections/<section>.js per section

Bound to 127.0.0.1 only: it can write bots and start jobs, so it is not for a network.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aflsim import paths
from aflsim.app import services as S
from aflsim.app.api import develop, inspect, jobs, live, media, play, aflhub as replayhub
from aflsim.app.jobs import JobManager


def _optional(module: str):
    """A private part of the platform (the analysis board, the Lab): None when this copy doesn't have it. Only a missing
    aflsim module counts as absent; any other failure is a real error and is raised."""
    import importlib
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as e:
        if (e.name or "").startswith("aflsim"):
            return None
        raise

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
SECTIONS = [                                                               # the browser builds its navigation from this
    {"id": "develop", "title": "Develop", "blurb": "Define and code teams"},
    {"id": "play", "title": "Play", "blurb": "Matches, tournaments, ratings"},
    {"id": "inspect", "title": "Inspect", "blurb": "Results and videos"},
    {"id": "lab", "title": "Lab", "blurb": "Experiments and agents (coming)"},
]


def create_app() -> FastAPI:
    app = FastAPI(title="afl_sim", version="0.1", docs_url="/api/docs")
    app.state.jobs = JobManager()
    sandbox = _optional("aflsim.analysis.sandbox")
    app.state.sandboxes = sandbox.Sessions() if sandbox else None          # open analysis-board sandboxes (in memory)
    private = [m for m in (_optional("aflsim.app.api.analysis"), _optional("aflsim.app.api.lab")) if m is not None]
    for r in (develop.router, play.router, inspect.router, media.router, jobs.router, live.router, replayhub.router,
              *[m.router for m in private], *[m.media_router for m in private if hasattr(m, "media_router")]):
        app.include_router(r)
    sections = [s for s in SECTIONS if s["id"] != "lab" or _optional("aflsim.app.api.lab") is not None]

    from fastapi.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware, minimum_size=50_000)                 # big JSON (timelines, broadcasts) travels compressed
    app.add_middleware(ContextMiddleware)

    @app.middleware("http")
    async def no_stale_code(request, call_next):
        """The page's own files are revalidated on every load, so a reload always runs the current code."""
        resp = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/api/meta")
    def meta():
        from aflsim.games import get_game
        g = get_game(S.game())
        return {"game": S.game(), "engine_version": S.engine(), "engine_latest": g.ENGINE_VERSION, "context": "%s.%d" % (S.game(), S.engine()),
                "contexts": S.contexts(), "features": S.features(), "n_per_team": g.make_rules().n_per_team,
                "default_seconds": g.DEFAULT_SECONDS, "sections": sections, "home": paths.home(), "zoo": sorted(g.ZOO), "anchors": list(g.ANCHORS)}

    @app.get("/media/videos/{rel:path}")
    def video(rel: str):
        try:
            p = S.safe_join(paths.videos_dir(S.game()), rel)
        except PermissionError:
            raise HTTPException(403, "no")
        if not os.path.isfile(p):
            raise HTTPException(404, rel)
        return FileResponse(p)

    @app.get("/")
    def index():
        """The page, pointing at /v/<version>/...: the version changes whenever any web file changes, so the browser
        can never run a stale copy of the app (relative imports inherit the versioned path)."""
        from fastapi.responses import HTMLResponse
        html = open(os.path.join(WEB, "index.html"), encoding="utf-8").read().replace("/static/", "/v/%s/" % web_version())
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    @app.get("/v/{version}/{rel:path}")
    def versioned(version: str, rel: str):
        try:
            p = S.safe_join(WEB, rel)
        except PermissionError:
            raise HTTPException(403, "no")
        if not os.path.isfile(p):
            raise HTTPException(404, rel)
        return FileResponse(p, headers={"Cache-Control": "public, max-age=31536000, immutable"})   # a new version = a new URL

    @app.get("/replayhub")
    @app.get("/replayhub/{rel:path}")
    def replayhub_file(rel: str = ""):
        """Serve the separately built 3D viewer under the app's own origin (and context cookie)."""
        dist = os.path.abspath(os.path.join(WEB, "..", "..", "..", "replayhub", "dist"))
        try:
            p = S.safe_join(dist, rel or "index.html")
        except PermissionError:
            raise HTTPException(403, "no")
        if not os.path.isfile(p):
            if not os.path.isdir(dist):
                raise HTTPException(404, "Build replayhub first: cd src/replayhub && npm install && npm run build")
            raise HTTPException(404, rel)
        return FileResponse(p, headers={"Cache-Control": "no-cache" if not rel else "public, max-age=31536000, immutable"})

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


COOKIE = "afl_ctx"


class ContextMiddleware:
    """Every request runs in the game and engine version the top bar picked (the afl_ctx cookie, e.g. "afl8.1"; an
    X-AFL-Context header wins, for scripts). Plain ASGI so the context variables reach the endpoint's thread."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from http.cookies import SimpleCookie
        from aflsim.games import reset_engine, use_engine
        headers = dict(scope.get("headers") or [])
        text = headers.get(b"x-afl-context", b"").decode() or None
        if text is None and b"cookie" in headers:
            c = SimpleCookie(); c.load(headers[b"cookie"].decode("latin-1"))
            text = c[COOKIE].value if COOKIE in c else None
        ctx = S.parse_context(text)
        if ctx is None:
            return await self.app(scope, receive, send)
        t1 = S._APPGAME.set(ctx[0]); t2 = use_engine(*ctx)
        try:
            return await self.app(scope, receive, send)
        finally:
            reset_engine(t2); S._APPGAME.reset(t1)


def web_version() -> str:
    """A short fingerprint of every web file's name, size and modification time."""
    import hashlib
    h = hashlib.sha1()
    for root, _d, files in os.walk(WEB):
        for f in sorted(files):
            st = os.stat(os.path.join(root, f))
            h.update(("%s|%d|%d;" % (os.path.join(root, f), st.st_size, st.st_mtime_ns)).encode())
    return h.hexdigest()[:10]


def main(host="127.0.0.1", port=8765, open_browser=True):
    import threading
    import webbrowser

    import uvicorn
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open("http://%s:%d/" % (host, port))).start()
    print("afl_sim app on http://%s:%d/  (Ctrl+C to stop; API docs at /api/docs)" % (host, port), flush=True)
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
