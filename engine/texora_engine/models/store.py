"""Model store: persists registry rows through ``db/`` and resolves ready models.

The store is the orchestration layer between the pinned :mod:`catalog`, the on-disk files,
and the ``model`` table. It never runs raw SQL (uses the ``db`` DAOs) and exposes
:meth:`require_ready` for the recognizer factory.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from texora_engine.db import ModelRow, get_model, upsert_model
from texora_engine.db.models_dao import set_status
from texora_engine.logging_config import get_logger
from texora_engine.models.catalog import catalog as build_catalog
from texora_engine.models.downloader import download_model, verify_file
from texora_engine.models.errors import ChecksumMismatch, ModelNotReady
from texora_engine.models.progress import (
    ModelDownloadState,
    ModelFileProgress,
    ModelProgress,
)
from texora_engine.models.registry import ModelSpec
from texora_engine.settings import Settings

logger = get_logger("models.store")

# Progress callback type alias.
ProgressSink = Callable[[ModelProgress], None]


class ModelStore:
    """Owns the pinned catalog + the ``model`` table for one engine instance."""

    def __init__(self, conn: sqlite3.Connection, settings: Settings) -> None:
        self._conn = conn
        self._settings = settings
        self._catalog: dict[str, ModelSpec] = build_catalog(settings.models_dir)

    def spec(self, model_id: str) -> ModelSpec:
        """Return the pinned spec for ``model_id`` (KeyError if unknown)."""

        return self._catalog[model_id]

    def known_ids(self) -> list[str]:
        """Return the ids of all pinned models."""

        return list(self._catalog)

    def _files_present_and_valid(self, spec: ModelSpec) -> bool:
        for f in spec.files:
            path = spec.file_path(f.name)
            if not path.exists():
                return False
            try:
                verify_file(path, f)
            except ChecksumMismatch:
                return False
        return True

    def status(self, model_id: str) -> ModelProgress:
        """Return the current :class:`ModelProgress` snapshot for ``model_id``.

        Reads the persisted row if present; otherwise reports ``downloading`` with zeroed
        counters only when a transfer is in-flight, else a synthetic ``error`` state is
        avoided by reporting the catalog defaults. Absent files map to ``downloading`` with
        received=0 so the UI can show a fresh fetch.
        """

        spec = self.spec(model_id)
        row = get_model(self._conn, model_id)
        per_file = [
            ModelFileProgress(
                name=f.name,
                received=f.size if (row and row.status == "ready") else 0,
                total=f.size,
            )
            for f in spec.files
        ]
        state = (
            ModelDownloadState.READY
            if row and row.status == "ready"
            else (
                ModelDownloadState.CORRUPT
                if row and row.status == "corrupt"
                else ModelDownloadState.DOWNLOADING
            )
        )
        return ModelProgress(
            id=model_id,
            state=state,
            bytes_received=sum(f.received for f in per_file),
            bytes_total=sum(f.total for f in per_file),
            files=per_file,
            detail=row.detail if row else None,
        )

    def _mark(self, spec: ModelSpec, status: str, detail: str | None = None) -> None:
        upsert_model(
            self._conn,
            ModelRow(
                id=spec.id,
                version=spec.version,
                status=status,
                license=spec.license,
                target_dir=str(spec.target_dir),
                sha256=None,
                size=sum(f.size for f in spec.files),
                detail=detail,
            ),
        )

    def ensure_ready(
        self,
        model_id: str,
        on_progress: ProgressSink | None = None,
    ) -> None:
        """Download ``model_id`` if needed, verify it, and persist a ``ready`` row.

        A checksum mismatch marks the row ``corrupt`` and re-raises so the caller can
        surface the error and offer a retry.
        """

        spec = self.spec(model_id)
        if self._files_present_and_valid(spec):
            self._mark(spec, "ready")
            return
        self._mark(spec, "downloading")
        try:
            download_model(spec, on_progress)
        except ChecksumMismatch as exc:
            logger.error("model %s corrupt: %s", model_id, exc)
            self._mark(spec, "corrupt", detail=str(exc))
            set_status(self._conn, model_id, "corrupt", detail=str(exc))
            raise
        except Exception as exc:  # network/IO — recoverable, offer retry
            logger.error("model %s download failed: %s", model_id, exc)
            self._mark(spec, "error", detail=str(exc))
            set_status(self._conn, model_id, "error", detail=str(exc))
            raise
        self._mark(spec, "ready")

    def require_ready(self, model_id: str) -> ModelSpec:
        """Return the spec for ``model_id`` only if its files are present and valid.

        Raises :class:`ModelNotReady` otherwise (the API maps this to a 409 so the UI can
        prompt a download).
        """

        spec = self.spec(model_id)
        if not self._files_present_and_valid(spec):
            raise ModelNotReady(model_id)
        self._mark(spec, "ready")
        return spec
