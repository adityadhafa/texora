"""``get_or_build_deps(app_state)`` tests (design §11, MEDIUM-F4, NIT-4) — no Request needed."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from texora_engine.db import init_db
from texora_engine.models.errors import ModelNotReady
from texora_engine.models.store import ModelStore
from texora_engine.pipeline.deps import get_or_build_deps
from texora_engine.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        token="t",
        log_dir=tmp_path / "logs",
        db_path=tmp_path / "db.sqlite",
        models_dir=tmp_path / "models",  # empty -> weights absent
    )


def _store(settings: Settings) -> ModelStore:
    return ModelStore(init_db(settings.db_path), settings)


def test_missing_pipeline_deps_attr_returns_none_not_attributeerror(tmp_path: Path) -> None:
    # An app_state that never ran create_app has NO pipeline_deps attr. The helper must tolerate
    # it (getattr(..., None)) and attempt a build rather than raise AttributeError.
    settings = _settings(tmp_path)
    app_state = SimpleNamespace(settings=settings, model_store=_store(settings))
    assert not hasattr(app_state, "pipeline_deps")
    with pytest.raises(ModelNotReady):
        # No downloaded weights -> the real factory raises ModelNotReady (the typed error the
        # route maps to 409). Crucially NOT AttributeError.
        get_or_build_deps(app_state)


def test_caches_built_deps_and_returns_same_instance(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    sentinel = object()
    app_state = SimpleNamespace(settings=settings, model_store=None, pipeline_deps=sentinel)
    # A pre-cached non-None pipeline_deps is returned verbatim (no rebuild).
    assert get_or_build_deps(app_state) is sentinel
