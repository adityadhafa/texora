"""Typed engine configuration via pydantic-settings.

Every value can be supplied by CLI args (see ``__main__``) or environment variables
prefixed with ``TEXORA_ENGINE_`` (e.g. ``TEXORA_ENGINE_TOKEN``). The engine binds
loopback only; ``host`` defaults to ``127.0.0.1`` and must stay non-routable.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
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
