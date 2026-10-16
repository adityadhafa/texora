"""Engine HTTP routes.

``health_router`` exposes an open liveness probe. ``protected_router`` exposes an
example route guarded by the bearer-token dependency so authentication has something to
protect. No OCR/ML logic lives here in M1.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from texora_engine import __version__
from texora_engine.security import require_token


class HealthResponse(BaseModel):
    """Payload returned by the open health check."""

    status: str = Field(default="ok", description="Liveness indicator.")


class EngineInfoResponse(BaseModel):
    """Payload returned by the protected engine-info route."""

    name: str = Field(description="Engine package name.")
    version: str = Field(description="Engine package version.")


health_router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(require_token)])


@health_router.get("/healthz", response_model=HealthResponse, tags=["health"])
def healthz() -> HealthResponse:
    """Open liveness probe; always returns 200 without authentication."""

    return HealthResponse(status="ok")


@protected_router.get("/engine/info", response_model=EngineInfoResponse, tags=["engine"])
def engine_info() -> EngineInfoResponse:
    """Return basic engine metadata. Requires a valid bearer token."""

    return EngineInfoResponse(name="texora-engine", version=__version__)
