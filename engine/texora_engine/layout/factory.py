"""Layout detector factory + typed errors (mirror of ``recognizers/factory.py``).

The pipeline depends on the :class:`~texora_engine.layout.base.LayoutDetector` Protocol, never on
a concrete adapter. The factory reads ``stages.layout`` from ``pipeline.yaml`` and builds the
matching adapter, resolving its weights through the model store by the adapter-declared
``model_ids`` — resolving **every** id in ``model_ids`` (not just the first), per design §2.1.
Misconfiguration raises typed errors the caller maps to a clear 500 — never a bare ``KeyError``
and never a silent default.

PERMISSIVE-ONLY REGISTRY (``R-LIC-2``): ``_REGISTRY`` contains ONLY the Apache-2.0
``pp_doclayout_onnx`` detector. The AGPL ``doclayout_yolo`` adapter is intentionally ABSENT — it
is opt-in only and reached through an explicit acknowledgment path, never the default factory.
``born_digital`` is NOT a registry id either: it is the assembler-owned structural fast-path
(design §3.1) with no ``model_ids`` and is never written into ``pipeline.yaml``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from texora_engine.layout.base import LayoutDetector
from texora_engine.layout.pp_doclayout_onnx import PpDocLayoutOnnxDetector
from texora_engine.logging_config import get_logger
from texora_engine.models.store import ModelStore
from texora_engine.pipeline_config import load_pipeline_config
from texora_engine.settings import Settings

logger = get_logger("layout.factory")


@dataclass(frozen=True)
class _Entry:
    """A registry entry: the adapter's declared ids + its constructor callable."""

    id: str
    model_ids: tuple[str, ...]
    ctor: Callable[..., LayoutDetector]


def _entry(ctor: type[PpDocLayoutOnnxDetector]) -> _Entry:
    # The class is the constructor callable; its instances satisfy LayoutDetector structurally
    # (asserted at runtime via isinstance in the factory test). mypy cannot prove a class object
    # matches a read-write-attribute Protocol, so narrow here once.
    return _Entry(
        id=ctor.id,
        model_ids=ctor.model_ids,
        ctor=cast("Callable[..., LayoutDetector]", ctor),
    )


# id -> entry. PERMISSIVE ONLY: pp_doclayout_onnx (Apache-2.0). doclayout_yolo (AGPL) is NOT here.
_REGISTRY: dict[str, _Entry] = {
    PpDocLayoutOnnxDetector.id: _entry(PpDocLayoutOnnxDetector),
}


class LayoutStageNotConfigured(Exception):
    """pipeline.yaml has no ``stages.layout`` engine id."""

    def __init__(self) -> None:
        super().__init__("pipeline.yaml does not configure stages.layout")


class UnknownLayoutEngineError(Exception):
    """pipeline.yaml names a layout engine id that is not registered."""

    def __init__(self, stage_id: str, known: list[str]) -> None:
        self.stage_id = stage_id
        self.known = known
        super().__init__(f"unknown layout engine id {stage_id!r}; known: {known}")


def register(ctor: type[PpDocLayoutOnnxDetector]) -> None:
    """Register an adapter constructor by its ``id`` (used by tests/plugins)."""

    _REGISTRY[ctor.id] = _entry(ctor)


def known_layout_engine_ids() -> list[str]:
    """Return the registered (permissive) layout engine ids."""

    return list(_REGISTRY)


def build_layout_detector(settings: Settings, model_store: ModelStore) -> LayoutDetector:
    """Build the configured layout detector with its weights resolved + local.

    Raises :class:`LayoutStageNotConfigured` when the key is absent/None and
    :class:`UnknownLayoutEngineError` when the id is not registered. Raises
    :class:`~texora_engine.models.errors.ModelNotReady` (from the store) when any required model
    is not downloaded yet — EVERY id in ``entry.model_ids`` is verified, not just the first
    (design §2.1).
    """

    stage_id = load_pipeline_config().stages.layout
    if stage_id is None:
        raise LayoutStageNotConfigured()
    if stage_id not in _REGISTRY:
        logger.error("unknown layout engine id %r; known=%s", stage_id, list(_REGISTRY))
        raise UnknownLayoutEngineError(stage_id, known=list(_REGISTRY))

    entry = _REGISTRY[stage_id]
    # Resolve weights via the adapter-declared model ids (dict-comprehension over EVERY id so a
    # missing model raises ModelNotReady, not just the first — design §2.1).
    specs = {mid: model_store.require_ready(mid) for mid in entry.model_ids}
    return entry.ctor(
        layout_onnx=specs["pp_doclayout"].file_path("doclayout.onnx"),
        label_map=specs["pp_doclayout"].file_path("label_map.txt"),
        device=settings.device,
    )
