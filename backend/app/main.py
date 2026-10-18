from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import metrics
from .config import REPO_DIR, get_settings
from .logging_setup import request_id_var, setup_logging
from .routers import admin, auth, findings, jury, quality, system, ui
from .state import AppState

log = logging.getLogger("backend")


def _raise_fd_limit() -> None:
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = 8192 if hard == resource.RLIM_INFINITY else min(8192, hard)
        if soft < want:
            resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
    except Exception:
        pass


def create_app() -> FastAPI:
    _raise_fd_limit()
    settings = get_settings()
    log_file = setup_logging(settings.storage_dir, settings.log_level, settings.log_json)
    state = AppState.build(settings, log_file=str(log_file))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        state.start()
        try:
            yield
        finally:
            state.stop()

    app = FastAPI(title="Forte PhantomGuard", version=settings.version, lifespan=lifespan,
                  docs_url="/docs", openapi_url="/openapi.json")
    app.state.st = state
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def _observe(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            if not request.url.path.startswith(("/api/", "/ui/api/", "/admin/", "/metrics")):
                response.headers["Cache-Control"] = "no-cache"
            return response
        finally:
            dt = time.perf_counter() - t0
            route = getattr(request.scope.get("route"), "path", None) or request.url.path
            if not route.startswith("/metrics"):
                metrics.HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
                metrics.HTTP_LATENCY.labels(route).observe(dt)
            if request.url.path.startswith(("/api/", "/ui/api/", "/admin/")) and not request.url.path.endswith(
                    ("/events", "/stream", "/mjpeg")):
                log.info("%s %s -> %d in %.0f ms", request.method, request.url.path, status, dt * 1000)
            request_id_var.reset(token)

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail, "status": exc.status_code,
                                     "request_id": request_id_var.get()},
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        missing_file = any(e.get("loc", ())[-1:] == ("file",) for e in errors)
        detail = "Ожидается multipart/form-data с полем file" if missing_file else "Некорректный запрос"
        return JSONResponse(status_code=400 if missing_file else 422,
                            content={"detail": detail, "errors": _plain(errors), "request_id": request_id_var.get()})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервиса",
                                                      "request_id": request_id_var.get()})

    app.include_router(jury.router)
    app.include_router(auth.router)
    app.include_router(findings.router)
    app.include_router(quality.router)
    app.include_router(ui.router)
    app.include_router(admin.router)
    app.include_router(system.router)
    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    dist = REPO_DIR / "frontend" / "dist"
    index = dist / "index.html"
    if not index.exists():
        @app.get("/", include_in_schema=False)
        def _no_frontend(request: Request):
            if _is_api_host(request):
                from .routers.jury import api_index
                return JSONResponse(api_index(request.app.state.st))
            return JSONResponse({"detail": "Frontend is not built: run `npm ci && npm run build` in frontend/ "
                                           "(or ./deploy/run_server.sh). The API is available under /api, /ui/api."})
        return
    app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def _spa(path: str, request: Request):
        st = request.app.state.st
        if _is_api_host(request):
            from .routers.jury import api_index
            if not path:
                return JSONResponse(api_index(st))
            return JSONResponse({"detail": "Not found", "status": 404}, status_code=404)
        candidate = (dist / path) if path else index
        if path and candidate.is_file() and dist in candidate.resolve().parents:
            return FileResponse(str(candidate))
        return FileResponse(str(index), headers={"Cache-Control": "no-cache"})


def _is_api_host(request: Request) -> bool:
    host = (request.headers.get("host") or "").split(":")[0].lower()
    return bool(host) and host in request.app.state.st.settings.api_hosts


def _plain(errors: list) -> list:
    out = []
    for e in errors:
        out.append({"loc": [str(x) for x in e.get("loc", ())], "msg": str(e.get("msg", "")), "type": e.get("type")})
    return out


app = create_app()
