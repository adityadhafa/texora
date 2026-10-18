"""PP-DocLayout ONNX detector tests.

The real model-backed test is ``@pytest.mark.model`` and skips-with-reason when the pinned ONNX
weights are not prefetched (never mocked). The failure-injection test proves the honesty invariant
WITHOUT weights: a corrupt/raising session must yield an empty :class:`LayoutResult`, never raise.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from texora_engine.ingest.base import RenderedPage, SourceKind
from texora_engine.layout.base import LayoutResult
from texora_engine.layout.pp_doclayout_onnx import PpDocLayoutOnnxDetector

from tests.conftest import prefetched_layout_models_dir


def _page(width: int = 640, height: int = 480) -> RenderedPage:
    return RenderedPage(
        index=0,
        width=width,
        height=height,
        dpi=260,
        kind=SourceKind.PDF_SCANNED,
        text_layer=None,
    )


@pytest.mark.model
def test_real_pp_doclayout_returns_typed_regions(tmp_path: Path) -> None:
    models_dir = prefetched_layout_models_dir()
    if models_dir is None:
        pytest.skip("pp_doclayout ONNX weights absent; run model prefetch")
    detector = PpDocLayoutOnnxDetector(
        layout_onnx=models_dir / "pp_doclayout" / "doclayout.onnx",
        label_map=models_dir / "pp_doclayout" / "label_map.txt",
        device="cpu",
    )
    image = Image.new("RGB", (640, 480), "white")
    result = detector.detect(image, _page())
    assert isinstance(result, LayoutResult)
    assert result.engine_id == "pp_doclayout_onnx"
    for r in result.regions:
        assert 0.0 <= r.confidence <= 1.0


def test_corrupt_session_returns_empty_result_never_raises(tmp_path: Path) -> None:
    """Failure injection: a session whose run() raises must yield regions=[] and not propagate."""

    # Build the detector WITHOUT touching onnxruntime (bypass __init__ model load) and inject a
    # fake session that raises on run() — simulating a corrupt/incompatible ONNX graph.
    detector = PpDocLayoutOnnxDetector.__new__(PpDocLayoutOnnxDetector)
    detector._device = "cpu"  # type: ignore[attr-defined]
    detector._label_map = {}  # type: ignore[attr-defined]

    class _ExplodingSession:
        def get_inputs(self):  # noqa: ANN202
            raise RuntimeError("corrupt onnx graph")

        def run(self, *_args: object, **_kwargs: object) -> object:
            raise RuntimeError("corrupt onnx graph")

    detector._session = _ExplodingSession()  # type: ignore[attr-defined]

    image = Image.new("RGB", (640, 480), "white")
    result = detector.detect(image, _page())

    assert result.regions == []
    assert result.engine_id == "pp_doclayout_onnx"
