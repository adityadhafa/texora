"""Application factory for the Texora engine.

``create_app`` builds a :class:`fastapi.FastAPI` instance, stores the expected bearer
token on ``app.state`` for the auth dependency, wires structured logging, and mounts the
open health router plus the token-protected router.
"""

from __future__ import annotations

from fastapi import FastAPI

from texora_engine import __version__
from texora_engine.api import health_router, protected_router
from texora_engine.logging_config import configure_logging
from texora_engine.settings import Settings


def create_app(settings: Settings) -> FastAPI:
    """Create and configure the engine FastAPI application."""

    logger = configure_logging(settings.log_dir, settings.log_level)

    app = FastAPI(
        title="Texora Engine",
        version=__version__,
        description="Offline OCR engine sidecar (loopback only).",
    )
    app.state.engine_token = settings.token

    app.include_router(health_router)
    app.include_router(protected_router)

    logger.info(
        "engine app created host=%s port=%s token_set=%s",
        settings.host,
        settings.port,
        bool(settings.token),
    )
    return app
