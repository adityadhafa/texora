"""Model-download progress contract.

``ModelProgress`` is returned by ``GET /models/{id}`` and forwarded verbatim by the Rust
supervisor on each ``engine://model-progress`` event. The TS mirror lives in
``apps/desktop/src/engineClient.ts`` (same literals, camelCase). See design §B.2b.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ModelDownloadState(StrEnum):
    """Lifecycle of a model download. READY/CORRUPT/ERROR are terminal."""

    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    READY = "ready"
    CORRUPT = "corrupt"
    ERROR = "error"


TERMINAL_STATES = frozenset(
    {ModelDownloadState.READY, ModelDownloadState.CORRUPT, ModelDownloadState.ERROR}
)


class ModelFileProgress(BaseModel):
    """Per-file byte progress."""

    name: str
    received: int = Field(ge=0, default=0)
    total: int = Field(ge=0, default=0)


class ModelProgress(BaseModel):
    """Overall + per-file progress for a model download."""

    id: str
    state: ModelDownloadState
    bytes_received: int = Field(ge=0, default=0)
    bytes_total: int = Field(ge=0, default=0)
    files: list[ModelFileProgress] = Field(default_factory=list)
    detail: str | None = None

    def is_terminal(self) -> bool:
        """True when the download has reached a terminal state."""

        return self.state in TERMINAL_STATES
