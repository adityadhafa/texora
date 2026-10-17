"""Settings defaults + env-override tests for the M2 fields."""

from __future__ import annotations

import pytest
from texora_engine.settings import Settings


def test_snip_defaults() -> None:
    s = Settings()
    assert s.max_snip_bytes == 8 * 1024 * 1024
    assert s.max_snip_pixels == 8_000_000
    assert s.max_snip_edge == 5000
    assert s.snip_timeout_s == 30.0
    assert s.snip_concurrency == 1
    assert s.device == "cpu"


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXORA_ENGINE_MAX_SNIP_BYTES", "1024")
    monkeypatch.setenv("TEXORA_ENGINE_DEVICE", "cuda")
    monkeypatch.setenv("TEXORA_ENGINE_SNIP_TIMEOUT_S", "5.5")
    s = Settings()
    assert s.max_snip_bytes == 1024
    assert s.device == "cuda"
    assert s.snip_timeout_s == 5.5
