"""pix2tex adapter tests.

The real-model test exercises the production path with the REAL model on a committed
fixture image (no mock). It skips with an explicit reason when weights are absent — it never
substitutes a fabricated output. A second test asserts the adapter refuses to construct
(ModelNotReady) when weights are absent and makes NO network call.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from PIL import Image
from texora_engine.models.errors import ModelNotReady
from texora_engine.recognizers.base import ConfidenceKind, RecognitionStatus, RegionContext
from texora_engine.recognizers.formula_pix2tex import Pix2TexFormulaRecognizer

from tests.conftest import prefetched_models_dir

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "formula_frac_ab.png"


def test_construct_without_weights_raises_and_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("adapter construction must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", _boom)

    with pytest.raises(ModelNotReady):
        Pix2TexFormulaRecognizer(
            checkpoint_path=tmp_path / "weights.pth",
            resizer_path=tmp_path / "image_resizer.pth",
            device="cpu",
        )


def test_real_model_recognizes_fixture() -> None:
    models_dir = prefetched_models_dir()
    if models_dir is None:
        pytest.skip("pix2tex weights absent; run model prefetch (see docs/m2-verification.md)")

    adapter = Pix2TexFormulaRecognizer(
        checkpoint_path=models_dir / "pix2tex" / "weights.pth",
        resizer_path=models_dir / "pix2tex" / "image_resizer.pth",
        device="cpu",
    )
    image = Image.open(_FIXTURE)
    result = adapter.recognize(image, RegionContext(is_display=True, device="cpu"))

    # Real model produced a non-empty LaTeX string via the production path (AC-4).
    assert result.status == RecognitionStatus.OK
    assert result.latex.strip() != ""
    assert result.engine_id == "pix2tex"
    # Confidence is honestly 'unavailable' on the pinned pix2tex (never fabricated).
    assert result.confidence == 0.0
    assert result.confidence_kind == ConfidenceKind.UNAVAILABLE
