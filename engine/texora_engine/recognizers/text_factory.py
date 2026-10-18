"""Text recognizer factory + the single-owning Tesseract-fallback decision (design §7.2.1).

The pipeline depends on the :class:`~texora_engine.recognizers.base.TextRecognizer` Protocol,
never on a concrete adapter. The factory reads ``stages.recognize.text`` from ``pipeline.yaml``
and builds the matching adapter, resolving its weights through the model store by the
adapter-declared ``model_ids`` — resolving **every** id in ``model_ids`` (not just the first,
design §2.1).

**One owning layer for the fallback (resolves F2).** ``model_store.require_ready`` raises
:class:`ModelNotReady` at *build time*, so the PP-OCRv5 → Tesseract degrade decision lives here
and nowhere else. The decision table (design §7.2.1):

| PP-OCRv5 weights | ``text_fallback_to_tesseract`` | Tesseract usable | Result |
|---|---|---|---|
| present | — | — | PP-OCRv5 adapter |
| absent | true | yes | Tesseract adapter (INFO-logged degrade) |
| absent | true | no | re-raise ``ModelNotReady`` → API 409 |
| absent | false | — | re-raise ``ModelNotReady`` → API 409 |

An explicitly-selected ``text: tesseract`` with a missing binary raises
:class:`TesseractUnavailable` (→ API 409), never a silent no-op and never a mock.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from texora_engine.logging_config import get_logger
from texora_engine.models.errors import ModelNotReady
from texora_engine.models.store import ModelStore
from texora_engine.pipeline_config import load_pipeline_config
from texora_engine.recognizers.base import TextRecognizer
from texora_engine.recognizers.text_ppocr_onnx import PpOcrV5TextRecognizer
from texora_engine.recognizers.text_tesseract import (
    TesseractTextRecognizer,
    TesseractUnavailable,
)
from texora_engine.settings import Settings

logger = get_logger("recognizers.text_factory")

_TESSERACT_ID = "tesseract"


@dataclass(frozen=True)
class _Entry:
    """A registry entry: the adapter's declared ids + its constructor callable."""

    id: str
    model_ids: tuple[str, ...]
    ctor: Callable[..., TextRecognizer]


def _pp_entry(ctor: type[PpOcrV5TextRecognizer]) -> _Entry:
    # mypy cannot prove a class object matches a read-write-attribute Protocol; narrow once.
    return _Entry(
        id=ctor.id,
        model_ids=ctor.model_ids,
        ctor=cast("Callable[..., TextRecognizer]", ctor),
    )


def _tess_entry(ctor: type[TesseractTextRecognizer]) -> _Entry:
    return _Entry(
        id=ctor.id,
        model_ids=ctor.model_ids,
        ctor=cast("Callable[..., TextRecognizer]", ctor),
    )


# id -> entry. Both adapters are permissive (PP-OCRv5 Apache-2.0, Tesseract Apache-2.0).
_REGISTRY: dict[str, _Entry] = {
    PpOcrV5TextRecognizer.id: _pp_entry(PpOcrV5TextRecognizer),
    TesseractTextRecognizer.id: _tess_entry(TesseractTextRecognizer),
}


class TextStageNotConfigured(Exception):
    """pipeline.yaml has no ``stages.recognize.text`` engine id."""

    def __init__(self) -> None:
        super().__init__("pipeline.yaml does not configure stages.recognize.text")


class UnknownTextEngineError(Exception):
    """pipeline.yaml names a text engine id that is not registered."""

    def __init__(self, stage_id: str, known: list[str]) -> None:
        self.stage_id = stage_id
        self.known = known
        super().__init__(f"unknown text engine id {stage_id!r}; known: {known}")


def register(ctor: type[PpOcrV5TextRecognizer] | type[TesseractTextRecognizer]) -> None:
    """Register an adapter constructor by its ``id`` (used by tests/plugins)."""

    _REGISTRY[ctor.id] = _Entry(
        id=ctor.id,
        model_ids=ctor.model_ids,
        ctor=cast("Callable[..., TextRecognizer]", ctor),
    )


def known_text_engine_ids() -> list[str]:
    """Return the registered text engine ids."""

    return list(_REGISTRY)


def _tesseract_available(settings: Settings) -> bool:
    """Whether the Tesseract binary resolves AND a version probe succeeds (design §7.2.1).

    The binary comes from ``settings.tesseract_cmd`` when set, else ``PATH``. A failed probe
    (missing binary / unusable install) returns ``False`` so the caller can decide 409 vs degrade.
    """

    import pytesseract

    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:  # EnvironmentError/TesseractNotFoundError/etc.
        logger.info("tesseract probe failed: %s", exc)
        return False
    return True


def _build_tesseract(settings: Settings) -> TextRecognizer:
    """Build the Tesseract adapter, raising :class:`TesseractUnavailable` when unusable.

    Used both for an explicit ``text: tesseract`` selection and for the PP-OCRv5 degrade path.
    """

    if not _tesseract_available(settings):
        raise TesseractUnavailable(settings.tesseract_cmd)
    return TesseractTextRecognizer(
        langs=("en", "id"),
        tesseract_cmd=settings.tesseract_cmd,
        data_dir=settings.tesseract_data_dir,
    )


def build_text_recognizer(settings: Settings, model_store: ModelStore) -> TextRecognizer:
    """Build the configured text recognizer, owning the single Tesseract-fallback decision.

    Raises :class:`TextStageNotConfigured` when the key is absent/None,
    :class:`UnknownTextEngineError` when the id is not registered,
    :class:`~texora_engine.recognizers.text_tesseract.TesseractUnavailable` when an explicit
    Tesseract selection has no usable binary, and re-raises
    :class:`~texora_engine.models.errors.ModelNotReady` when PP-OCRv5 weights are absent and no
    usable fallback is available (the API maps both to 409).
    """

    stage_id = load_pipeline_config().stages.recognize.text
    if stage_id is None:
        raise TextStageNotConfigured()
    if stage_id not in _REGISTRY:
        logger.error("unknown text engine id %r; known=%s", stage_id, list(_REGISTRY))
        raise UnknownTextEngineError(stage_id, known=list(_REGISTRY))

    # Explicitly-selected Tesseract: no model-store resolution (model_ids == ()).
    if stage_id == _TESSERACT_ID:
        return _build_tesseract(settings)

    entry = _REGISTRY[stage_id]
    try:
        # Resolve EVERY id so a missing model raises ModelNotReady, not just the first (§2.1).
        specs = {mid: model_store.require_ready(mid) for mid in entry.model_ids}
    except ModelNotReady:
        if settings.text_fallback_to_tesseract and _tesseract_available(settings):
            logger.info("text degrade: PP-OCRv5 weights absent -> falling back to tesseract")
            return _build_tesseract(settings)
        raise  # -> api/pages.py maps to 409 (prompt download)

    return entry.ctor(
        det_onnx=specs["pp_ocrv5_det"].file_path("det.onnx"),
        rec_onnx=specs["pp_ocrv5_rec"].file_path("rec.onnx"),
        dict_path=specs["pp_ocrv5_rec"].file_path("rec_keys.txt"),
        langs=("en", "id"),
        device=settings.device,
    )
