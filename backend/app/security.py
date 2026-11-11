from __future__ import annotations

import hmac

from fastapi import Header, Request

from .errors import ApiError


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    expected = request.app.state.settings.api_key.get_secret_value()
    if x_api_key is None or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise ApiError(401, "UNAUTHORIZED", "A valid X-API-Key header is required.")
