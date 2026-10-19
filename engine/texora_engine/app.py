"""Application factory for the Texora engine.

``create_app`` builds a :class:`fastapi.FastAPI` instance, stores the expected bearer token
and runtime settings on ``app.state``, opens the SQLite database and model store, wires
structured logging, applies the Pillow decompression-bomb backstop, and mounts the open
health router plus the token-protected routers (engine info, recognize, hardware, models).
"""

from __future__ import annotations

import asyncio

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
from texora_engine.api.jobs import jobs_router, jobs_ws_router
from texora_engine.db import init_db
from texora_engine.jobs.manager import JobManager
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
    app.state.job_manager = None  # constructed on startup (needs the running event loop)
    app.state.watch_observer = None  # watchdog Observer, started on startup if configured

    app.include_router(health_router)
    app.include_router(protected_router)
    app.include_router(recognize_router)
    app.include_router(hardware_router)
    app.include_router(models_router)
    app.include_router(pages_router)
    app.include_router(jobs_router)
    app.include_router(jobs_ws_router)

    @app.on_event("startup")
    async def _startup() -> None:
        # Build the JobManager on the running loop, recover orphaned leases, start the sweeper.
        manager = JobManager(
            conn,
            app_state=app.state,
            settings=settings,
            loop=asyncio.get_event_loop(),
        )
        app.state.job_manager = manager
        manager.recover_on_boot()
        manager.start_sweeper()
        logger.info("job manager started; recovered orphaned leases")

        if settings.watch_dir is not None:
            from texora_engine.jobs.watch import start_watch_observer

            try:
                app.state.watch_observer = start_watch_observer(
                    manager, settings.watch_dir, asyncio.get_event_loop()
                )
            except OSError as exc:
                logger.warning(
                    "watch-folder observer failed to start on %s: %s", settings.watch_dir, exc
                )

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        manager = getattr(app.state, "job_manager", None)
        if manager is not None:
            await manager.shutdown()
        observer = getattr(app.state, "watch_observer", None)
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)

    logger.info(
        "engine app created host=%s port=%s token_set=%s db=%s",
        settings.host,
        settings.port,
        bool(settings.token),
        settings.db_path,
    )
    return app
