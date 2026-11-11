from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from backend.core import hardware
from backend.core.imaging import IMAGE_KEYS
from backend.core.idempotency import fetch

from .errors import ApiError
from .schemas import build_input
from .security import require_api_key

router = APIRouter()
STATIC = Path(__file__).resolve().parent.parent / "static"
FILE_FIELDS = {k: k for k in IMAGE_KEYS}


async def _read_form(request: Request, max_bytes: int) -> tuple[dict[str, str], dict[str, bytes]]:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > len(IMAGE_KEYS) * max_bytes + 200_000:
        raise ApiError(422, "IMAGE_TOO_LARGE", "The request is larger than the allowed upload size.")
    form = await request.form()
    fields: dict[str, str] = {}
    images: dict[str, bytes] = {}
    for key, value in form.multi_items():
        if isinstance(value, UploadFile):
            if key in FILE_FIELDS:
                data = await value.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ApiError(422, "IMAGE_TOO_LARGE", f"Image {key} is larger than {max_bytes} bytes.")
                images[key] = data
        else:
            fields[key] = value
    for k in IMAGE_KEYS:
        if k not in images or not images[k]:
            raise ApiError(422, "MISSING_FIELD", f"Image {k} is required.")
    return fields, images


@router.post("/v1/verify", dependencies=[Depends(require_api_key)])
async def verify(request: Request) -> JSONResponse:
    gate = request.app.state.gate
    if not gate.try_acquire():
        raise ApiError(
            503, "BUSY", "A verification is already running.",
            {"Retry-After": str(request.app.state.settings.retry_after_s)},
        )
    try:
        fields, images = await _read_form(request, request.app.state.settings.max_upload_bytes)
        inp = build_input(fields, images)
        response = await run_in_threadpool(request.app.state.engine.verify, inp)
        return JSONResponse(response)
    finally:
        gate.release()


@router.get("/v1/sessions/{request_id}", dependencies=[Depends(require_api_key)])
async def get_session(request_id: str, request: Request) -> JSONResponse:
    stored = fetch(request.app.state.engine.store, request_id)
    if stored is None:
        raise ApiError(404, "NOT_FOUND", "No stored result for this request_id.")
    return JSONResponse(stored)


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    info = request.app.state.engine.health_info()
    loaded = info.get("models_loaded", {})
    required = [v for k, v in loaded.items() if k != "liveness"]
    return JSONResponse(
        {"status": "ok" if all(required) else "degraded", "models_loaded": loaded, "rss_mb": round(hardware.rss_mb(), 1)},
        status_code=200 if all(required) else 503,
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@router.get("/")
async def index() -> FileResponse:
    page = STATIC / "index.html"
    if not page.exists():
        raise ApiError(404, "NOT_FOUND", "Test page not installed.")
    return FileResponse(page, media_type="text/html")
