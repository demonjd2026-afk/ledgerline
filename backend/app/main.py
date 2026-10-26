from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text

from app.api.routes import router as api_router
from app.config import get_settings
from app.db import get_engine
from app.ingest.webhooks import router as webhook_router
from app.logging import configure_logging, get_logger
from app.paypal.client import PayPalClient

log = get_logger("api")
REQS = Counter("ledgerline_http_requests_total", "HTTP requests", ["method", "path", "status"])
LAT = Histogram("ledgerline_http_request_seconds", "HTTP latency", ["path"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    from app.agents.runner import ensure_checkpointer

    ensure_checkpointer()
    log.info("api.start", env=get_settings().app_env, paypal=get_settings().paypal_configured)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Ledgerline", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def _observe(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=rid)
        t0 = time.perf_counter()
        try:
            response: Response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        path = request.url.path if not request.url.path.startswith("/api/") else "/api/" + request.url.path.split("/")[2]
        REQS.labels(request.method, path, response.status_code).inc()
        LAT.labels(path).observe(time.perf_counter() - t0)
        response.headers["x-request-id"] = rid
        return response

    app.include_router(webhook_router)
    app.include_router(api_router)

    @app.get("/healthz")
    def healthz() -> dict:
        db_ok = True
        try:
            with get_engine().connect() as c:
                c.execute(text("select 1"))
        except Exception:  # noqa: BLE001
            db_ok = False
        pp_ok = PayPalClient().healthcheck() if s.paypal_configured else None
        return {"ok": db_ok and pp_ok is not False, "db": db_ok, "paypal": pp_ok, "env": s.paypal_env}

    @app.get("/metrics")
    def metrics() -> Response:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    dist: Path = s.frontend_dist
    if s.serve_frontend and dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            target = dist / full_path
            if full_path and target.is_file():
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
