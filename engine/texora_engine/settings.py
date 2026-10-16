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
