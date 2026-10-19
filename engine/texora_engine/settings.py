"""Typed engine configuration via pydantic-settings.

Every value can be supplied by CLI args (see ``__main__``) or environment variables
prefixed with ``TEXORA_ENGINE_`` (e.g. ``TEXORA_ENGINE_TOKEN``). The engine binds
loopback only; ``host`` defaults to ``127.0.0.1`` and must stay non-routable.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the Texora engine sidecar."""

    model_config = SettingsConfigDict(
        env_prefix="TEXORA_ENGINE_",
        env_file=None,
        extra="ignore",
    )

    host: str = Field(default="127.0.0.1", description="Loopback bind address.")
    port: int = Field(default=8756, ge=1, le=65535, description="TCP port to bind.")
    token: str = Field(
        default="",
        description="Bearer token required on every non-health route.",
    )
    log_dir: Path = Field(
        default=Path("logs"),
        description="Directory for rotating log files.",
    )
    log_level: str = Field(default="INFO", description="Root log level for the engine.")

    # --- Storage (M2) ---
    db_path: Path = Field(
        default=Path("texora.db"),
        description="SQLite database file (WAL) for the MODEL and SETTING tables.",
    )
    models_dir: Path = Field(
        default=Path("models"),
        description="Root directory where downloaded model weights are stored.",
    )

    # --- Hardware (M2) ---
    device: str = Field(
        default="cpu",
        description="Execution device for recognition: cpu|cuda|mps.",
    )

    # --- Snip recognition guards (M2) ---
    max_snip_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=1,
        description="Maximum decoded base64 image size in bytes before rejecting a snip (422).",
    )
    max_snip_pixels: int = Field(
        default=8_000_000,
        ge=1,
        description="Maximum decoded image area (width*height) — decompression-bomb guard (422).",
    )
    max_snip_edge: int = Field(
        default=5000,
        ge=1,
        description="Maximum decoded image edge length in pixels — decompression-bomb guard (422).",
    )
    snip_timeout_s: float = Field(
        default=30.0,
        gt=0,
        description="Per-snip recognition timeout in seconds; a timeout returns status=failed.",
    )
    snip_concurrency: int = Field(
        default=1,
        ge=1,
        description="Worker pool size for snip inference. 1 serializes the shared torch model.",
    )

    # --- Page/region recognition guards (M3) ---
    region_timeout_s: float = Field(
        default=30.0,
        gt=0,
        description="Per-region recognition timeout in seconds; a timeout marks the region failed.",
    )
    region_concurrency: int = Field(
        default=1,
        ge=1,
        description="Worker pool size for per-region inference. 1 serializes the shared models.",
    )

    # --- Text recognition (M3) ---
    text_fallback_to_tesseract: bool = Field(
        default=True,
        description="Fall back to the Tesseract text adapter when the PP-OCRv5 model is absent.",
    )
    tesseract_cmd: str | None = Field(
        default=None,
        description="Absolute path to the tesseract binary; None resolves it on PATH.",
    )
    tesseract_data_dir: str | None = Field(
        default=None,
        description="Optional tessdata directory (traineddata); None uses the system default.",
    )

    # --- Export (M3) ---
    export_preamble: str = Field(
        default="article",
        description="LaTeX preamble template name used by the .tex exporter.",
    )
    figure_asset_dir: Path = Field(
        default=Path("assets"),
        description="Directory (relative to the export target) for extracted figure assets.",
    )

    # --- Job queue (M4, design §3.4) ---
    job_max_concurrent_pages: int = Field(
        default=2,
        ge=1,
        le=64,
        description="Global in-flight page cap across all jobs (the memory valve).",
    )
    job_page_workers: int = Field(
        default=1,
        ge=1,
        le=64,
        description=(
            "Thread-pool size for assemble_page. 1 serializes the shared torch model (HIGH-2); "
            ">1 is an M7 seam gated on a per-model inference lock."
        ),
    )
    job_lease_ttl_s: float = Field(
        default=300.0,
        gt=0,
        description="Lease lifetime; a crashed lease older than this reverts. Must be > timeout.",
    )
    job_page_timeout_s: float = Field(
        default=120.0,
        gt=0,
        description="Whole-page wall-clock timeout. Must be < job_lease_ttl_s (HIGH-3).",
    )
    job_lease_sweep_s: float = Field(
        default=30.0,
        gt=0,
        description="Interval of the background expired-lease sweeper (an asyncio task).",
    )
    job_output_dir: Path = Field(
        default=Path("output"),
        description="Root directory for streamed per-page export artifacts.",
    )
    watch_dir: Path | None = Field(
        default=None,
        description="Watch-folder path; None disables watch mode.",
    )
    watch_settle_s: float = Field(
        default=2.0,
        gt=0,
        description="Quiet period a new file must be size-stable before enqueue.",
    )
    ws_token_timeout_s: float = Field(
        default=5.0,
        gt=0,
        description="Fallback-path wait for the first WS token frame before close(4401).",
    )

    @model_validator(mode="after")
    def _validate_timeout_lt_lease(self) -> Settings:
        """Enforce ``job_page_timeout_s < job_lease_ttl_s`` (design §3.4, HIGH-3).

        This is the invariant that makes lease renewal unnecessary: a live page is force-failed
        by its wall-clock timeout strictly before its lease could expire, so the sweeper only ever
        reclaims a crashed lease.
        """

        if self.job_page_timeout_s >= self.job_lease_ttl_s:
            raise ValueError(
                "job_page_timeout_s must be < job_lease_ttl_s "
                f"(got {self.job_page_timeout_s} >= {self.job_lease_ttl_s})"
            )
        return self
