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


def test_m3_defaults() -> None:
    s = Settings()
    assert s.region_timeout_s == 30.0
    assert s.region_concurrency == 1
    assert s.text_fallback_to_tesseract is True
    assert s.tesseract_cmd is None
    assert s.tesseract_data_dir is None
    assert s.export_preamble == "article"
    assert str(s.figure_asset_dir) == "assets"


def test_m3_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXORA_ENGINE_REGION_TIMEOUT_S", "12.5")
    monkeypatch.setenv("TEXORA_ENGINE_TEXT_FALLBACK_TO_TESSERACT", "false")
    monkeypatch.setenv("TEXORA_ENGINE_TESSERACT_CMD", "/usr/bin/tesseract")
    monkeypatch.setenv("TEXORA_ENGINE_EXPORT_PREAMBLE", "amsart")
    s = Settings()
    assert s.region_timeout_s == 12.5
    assert s.text_fallback_to_tesseract is False
    assert s.tesseract_cmd == "/usr/bin/tesseract"
    assert s.export_preamble == "amsart"
