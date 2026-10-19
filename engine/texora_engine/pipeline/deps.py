"""Request-free shared :class:`PipelineDeps` provider (design §11, M4-ADR-10).

Both the synchronous ``api/pages._get_deps(request)`` wrapper and the async job runner build the
pipeline engines through this single helper so they share ONE cached deps instance — one set of
loaded models, constant memory. The helper takes Starlette ``app.state`` (NOT a FastAPI
``Request``) so the runner, which has no request, can call it, and it tolerates a missing/None
``pipeline_deps`` attribute (NIT-4). It raises the SAME typed errors the route maps to 409/500:
``ModelNotReady`` / ``TesseractUnavailable`` / the factory misconfiguration errors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from texora_engine.layout.factory import build_layout_detector
from texora_engine.pipeline.assembler import PipelineDeps
from texora_engine.pipeline_config import load_pipeline_config
from texora_engine.recognizers.factory import build_formula_recognizer
from texora_engine.recognizers.text_factory import build_text_recognizer


def _build_deps(settings: Any, store: Any) -> PipelineDeps:
    """Build the layout/text/formula engines + pipeline config (may raise the typed errors)."""

    cfg = load_pipeline_config()
    return PipelineDeps(
        layout=build_layout_detector(settings, store),
        text=build_text_recognizer(settings, store),
        formula=build_formula_recognizer(settings, store),
        settings=settings,
        pipeline_config=cfg,
        asset_dir=Path(settings.figure_asset_dir),
    )


def get_or_build_deps(app_state: Any) -> PipelineDeps:
    """Return the cached :class:`PipelineDeps` or build + cache it on ``app_state.pipeline_deps``.

    Reads ``app_state.{settings, model_store}`` (both must be seeded by the caller) and caches on
    ``app_state.pipeline_deps``. Uses ``getattr(..., None)``/``setattr`` so an ``app_state`` that
    never ran ``create_app`` (the runner / unit tests) returns ``None`` instead of raising
    ``AttributeError``.
    """

    cached: PipelineDeps | None = getattr(app_state, "pipeline_deps", None)
    if cached is not None:
        return cached
    deps = _build_deps(app_state.settings, app_state.model_store)
    app_state.pipeline_deps = deps
    return deps
