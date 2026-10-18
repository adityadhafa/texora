"""Application factory for the Texora engine.

``create_app`` builds a :class:`fastapi.FastAPI` instance, stores the expected bearer token
and runtime settings on ``app.state``, opens the SQLite database and model store, wires
structured logging, applies the Pillow decompression-bomb backstop, and mounts the open
health router plus the token-protected routers (engine info, recognize, hardware, models).
"""

from __future__ import annotations

from fastapi import FastAPI
from PIL import Image

from texora_engine import __version__
from texora_engine.api import (
    hardware_router,
    health_router,
    models_router,
    pages_router,
    protected_router,
    recognize_router,
)
from texora_engine.db import init_db
from texora_engine.logging_config import configure_logging
from texora_engine.models.store import ModelStore
from texora_engine.settings import Settings


def create_app(settings: Settings) -> FastAPI:
    """Create and configure the engine FastAPI application."""

    logger = configure_logging(settings.log_dir, settings.log_level)

    # Decompression-bomb backstop (route-level guards also bound decoded dimensions).
    Image.MAX_IMAGE_PIXELS = settings.max_snip_pixels

    app = FastAPI(
        title="Texora Engine",
        version=__version__,
        description="Offline OCR engine sidecar (loopback only).",
    )
    app.state.engine_token = settings.token
    app.state.settings = settings

    # Open DB + model store once; share via app.state. The recognizer singleton is built
    # lazily on first use (it needs downloaded weights).
    conn = init_db(settings.db_path)
    app.state.db = conn
    app.state.model_store = ModelStore(conn, settings)
    app.state.formula_recognizer = None  # cached singleton, set on first /recognize/snip
    app.state.pipeline_deps = None  # cached PipelineDeps, set on first /pages/recognize

    app.include_router(health_router)
    app.include_router(protected_router)
    app.include_router(recognize_router)
    app.include_router(hardware_router)
    app.include_router(models_router)
    app.include_router(pages_router)

    logger.info(
        "engine app created host=%s port=%s token_set=%s db=%s",
        settings.host,
        settings.port,
        bool(settings.token),
        settings.db_path,
    )
    return app
