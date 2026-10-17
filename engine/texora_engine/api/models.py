"""Model status + download routes.

``GET /models/{id}`` returns the current :class:`ModelProgress`. ``POST /models/{id}/download``
starts the server-side download as a background task and returns the initial ``downloading``
status immediately (non-blocking) — interim byte progress + the terminal state are observed
by the Rust supervisor polling ``GET /models/{id}`` and emitting ``engine://model-progress``.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from texora_engine.logging_config import get_logger
from texora_engine.models.progress import (
    ModelDownloadState,
    ModelFileProgress,
    ModelProgress,
)
from texora_engine.models.store import ModelStore
from texora_engine.security import require_token

logger = get_logger("api.models")

models_router = APIRouter(dependencies=[Depends(require_token)], tags=["models"])


def _store(request: Request) -> ModelStore:
    store: ModelStore = request.app.state.model_store
    return store


@models_router.get("/models/{model_id}", response_model=ModelProgress)
def get_model_status(model_id: str, request: Request) -> ModelProgress:
    """Return the current progress/status for ``model_id``."""

    store = _store(request)
    try:
        return store.status(model_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown model id {model_id!r}",
        ) from exc


@models_router.post("/models/{model_id}/download", response_model=ModelProgress)
def start_model_download(
    model_id: str, request: Request, background: BackgroundTasks
) -> ModelProgress:
    """Start a background download and return the initial ``downloading`` status."""

    store = _store(request)
    try:
        spec = store.spec(model_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown model id {model_id!r}",
        ) from exc

    def _run() -> None:
        try:
            store.ensure_ready(model_id)
        except Exception as exc:  # errors are persisted on the row; poller surfaces them
            logger.error("background download of %s failed: %s", model_id, exc)

    background.add_task(_run)

    files = [ModelFileProgress(name=f.name, received=0, total=f.size) for f in spec.files]
    return ModelProgress(
        id=model_id,
        state=ModelDownloadState.DOWNLOADING,
        bytes_received=0,
        bytes_total=sum(f.size for f in spec.files),
        files=files,
    )
