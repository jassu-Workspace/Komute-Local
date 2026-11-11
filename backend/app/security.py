from __future__ import annotations

import hmac

from fastapi import Header, Request

from .errors import ApiError


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Enforced only when KOMUTE_API_KEY is set. With no key configured the API is open (local testing)."""
    key = request.app.state.settings.api_key
    if key is None:
        return
    if x_api_key is None or not hmac.compare_digest(x_api_key.encode(), key.get_secret_value().encode()):
        raise ApiError(401, "UNAUTHORIZED", "A valid X-API-Key header is required.")
