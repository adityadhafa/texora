"""Typed models for the job runner/manager (design §3.3, §9.1).

These Pydantic v2 models are the stable contract between the runner, the control API, and the WS
progress stream. ``JobOptions`` is stored as ``job.options_json``; ``JobProgress`` is computed from
``pages_dao.counts`` plus an in-memory EWMA; ``ProgressEvent`` is pushed to WS subscribers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobOptions(BaseModel):
    """Per-job options: which pages to process + export/render settings.

    Exactly one page-selection mode is honored, in precedence order: an explicit ``pages`` list,
    then a ``page_start``/``page_end`` range, else the whole document. Out-of-range indices are
    dropped at enrollment with a logged note (design §10), never an error.
    """

    dpi: int | None = Field(default=None, description="Optional render-DPI override.")
    page_start: int | None = Field(default=None, ge=0, description="First 0-based index (incl).")
    page_end: int | None = Field(default=None, ge=0, description="Last 0-based index (incl).")
    pages: list[int] | None = Field(
        default=None, description="Explicit 0-based index list (overrides range when set)."
    )
    formats: list[str] = Field(
        default_factory=lambda: ["md"],
        description="Export formats to materialize per page (md|tex|json).",
    )


class JobProgress(BaseModel):
    """Live progress for a job (counts are authoritative; rate/ETA are best-effort)."""

    total: int = 0
    pending: int = 0
    leased: int = 0
    done: int = 0
    failed: int = 0
    needs_review: int = 0
    pages_per_min: float | None = Field(default=None, description="EWMA throughput; None early.")
    eta_seconds: float | None = Field(default=None, description="Remaining / rate; None early.")


class ProgressEvent(BaseModel):
    """One WS progress event emitted on each page completion + on state changes (design §9.3)."""

    job_id: str
    status: str = Field(description="The job lifecycle status after this event.")
    page_index: int | None = Field(default=None, description="The page that just completed.")
    page_status: str | None = Field(default=None, description="done|failed for page_index.")
    progress: JobProgress
    error: str | None = Field(default=None, description="Terminal job error, if any.")
    terminal: bool = Field(default=False, description="True on a final done|failed|canceled event.")
