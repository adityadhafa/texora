"""Formula recognizer factory + typed errors.

The route depends on the :class:`FormulaRecognizer` Protocol, never on a concrete adapter.
The factory reads ``stages.recognize.formula`` from ``pipeline.yaml`` and builds the
matching adapter, resolving its weights through the model store by the adapter-declared
``model_ids`` (not ``adapter.id == model.id``). Misconfiguration raises typed errors the
route maps to a clear 500 — never a bare ``KeyError`` and never a silent default.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from texora_engine.logging_config import get_logger
from texora_engine.models.store import ModelStore
from texora_engine.pipeline_config import load_pipeline_config
from texora_engine.recognizers.base import FormulaRecognizer
from texora_engine.recognizers.formula_pix2tex import Pix2TexFormulaRecognizer
from texora_engine.settings import Settings

logger = get_logger("recognizers.factory")


@dataclass(frozen=True)
class _Entry:
    """A registry entry: the adapter's declared ids + its constructor callable."""

    id: str
    model_ids: tuple[str, ...]
    ctor: Callable[..., FormulaRecognizer]


def _entry(ctor: type[Pix2TexFormulaRecognizer]) -> _Entry:
    # The class is the constructor callable; its instances satisfy FormulaRecognizer
    # structurally (asserted at runtime via isinstance in the factory test). mypy cannot
    # prove a class object matches a read-write-attribute Protocol, so narrow here once.
    return _Entry(
        id=ctor.id,
        model_ids=ctor.model_ids,
        ctor=cast("Callable[..., FormulaRecognizer]", ctor),
    )


# id -> entry. A new engine is added by dropping a file here + one pipeline.yaml line.
_REGISTRY: dict[str, _Entry] = {
    Pix2TexFormulaRecognizer.id: _entry(Pix2TexFormulaRecognizer),
}


class FormulaStageNotConfigured(Exception):
    """pipeline.yaml has no ``stages.recognize.formula`` engine id."""

    def __init__(self) -> None:
        super().__init__("pipeline.yaml does not configure stages.recognize.formula")


class UnknownEngineError(Exception):
    """pipeline.yaml names a formula engine id that is not registered."""

    def __init__(self, stage_id: str, known: list[str]) -> None:
        self.stage_id = stage_id
        self.known = known
        super().__init__(f"unknown formula engine id {stage_id!r}; known: {known}")


def register(ctor: type[Pix2TexFormulaRecognizer]) -> None:
    """Register an adapter constructor by its ``id`` (used by tests/plugins)."""

    _REGISTRY[ctor.id] = _entry(ctor)


def known_engine_ids() -> list[str]:
    """Return the registered formula engine ids."""

    return list(_REGISTRY)


def build_formula_recognizer(settings: Settings, model_store: ModelStore) -> FormulaRecognizer:
    """Build the configured formula recognizer with its weights resolved + local.

    Raises :class:`FormulaStageNotConfigured` when the key is absent/None and
    :class:`UnknownEngineError` when the id is not registered. Raises
    :class:`~texora_engine.models.errors.ModelNotReady` (from the store) when weights are
    not downloaded yet.
    """

    stage_id = load_pipeline_config().stages.recognize.formula
    if stage_id is None:
        raise FormulaStageNotConfigured()
    if stage_id not in _REGISTRY:
        logger.error("unknown formula engine id %r; known=%s", stage_id, list(_REGISTRY))
        raise UnknownEngineError(stage_id, known=list(_REGISTRY))

    entry = _REGISTRY[stage_id]
    # Resolve weights via the adapter-declared model id (not adapter.id == model.id).
    spec = model_store.require_ready(entry.model_ids[0])
    return entry.ctor(
        checkpoint_path=spec.file_path("weights.pth"),
        resizer_path=spec.file_path("image_resizer.pth"),
        device=settings.device,
    )
