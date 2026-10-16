"""Bearer-token authentication for non-health engine routes.

The expected token is stored on ``app.state`` by :func:`texora_engine.app.create_app`.
``require_token`` is a FastAPI dependency that reads the ``Authorization: Bearer <token>``
header and compares it to the expected value in constant time. A missing or mismatched
token yields ``401``.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing bearer token.",
    headers={"WWW-Authenticate": "Bearer"},
)


def require_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """Reject the request unless a valid bearer token is supplied.

    Raises ``401`` when the ``Authorization`` header is absent, not a Bearer credential,
    or does not match the expected token (compared with :func:`secrets.compare_digest`).
    """

    expected: str = getattr(request.app.state, "engine_token", "")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _UNAUTHORIZED

    if not expected or not secrets.compare_digest(credentials.credentials, expected):
        raise _UNAUTHORIZED
