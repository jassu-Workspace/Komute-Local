"""FastAPI wrapper. Run with:  uvicorn backend.app.main:create_app --factory --workers 1"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.core.config import Settings, get_settings
from backend.core.idempotency import IdempotencyConflict
from backend.core.contracts import EngineError, InputError
from backend.core.pipeline import Engine, build_engine
from storage.retention import RetentionPolicy, sweep

from .errors import ApiError, error_response
from .gate import RunGate
from .routes import router

log = logging.getLogger("komute.api")

# The test page is one file with inline script and style, so those two are allowed; nothing else loads from anywhere.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data: blob:; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}


def _sweeper(engine: Engine, settings: Settings, stop: threading.Event) -> None:
    policy = RetentionPolicy(
        rejected_images=timedelta(hours=settings.rejected_images_ttl_h),
        approved_originals=timedelta(days=settings.approved_originals_ttl_d),
    )
    while True:
        try:
            sweep(engine.store, datetime.now(timezone.utc), policy)
        except Exception as e:  # a failed sweep must never take the service down; it retries next interval
            log.error("retention sweep failed type=%s", type(e).__name__)
        if stop.wait(settings.sweep_interval_s):
            return


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "engine", None) is None:
            app.state.engine = build_engine(settings)  # fails startup closed if models or keys are wrong
        thread = threading.Thread(target=_sweeper, args=(app.state.engine, settings, stop), daemon=True)
        thread.start()
        yield
        stop.set()

    app = FastAPI(title="Komute-Local", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.gate = RunGate()
    if settings.api_key is None:
        log.warning("authentication is OFF: no KOMUTE_API_KEY set (local testing only)")
    app.state.engine = engine
    app.include_router(router)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError) -> JSONResponse:
        return error_response(e.status, e.code, e.message, e.headers)

    @app.exception_handler(InputError)
    async def _input_error(_: Request, e: InputError) -> JSONResponse:
        return error_response(422, e.code, "The image could not be read. Upload a JPEG, PNG or WebP photo.")

    @app.exception_handler(IdempotencyConflict)
    async def _conflict(_: Request, e: IdempotencyConflict) -> JSONResponse:
        return error_response(409, "REQUEST_ID_CONFLICT", "This request_id was already used with different data.")

    @app.exception_handler(EngineError)
    async def _engine_error(_: Request, e: EngineError) -> JSONResponse:
        return error_response(500, "ENGINE_ERROR", "The verification could not be completed. No decision was made.")

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, e: Exception) -> JSONResponse:
        log.error("unhandled type=%s", type(e).__name__)
        return error_response(500, "ENGINE_ERROR", "The verification could not be completed. No decision was made.")

    return app
