"""Model registry + catalog tests."""

from __future__ import annotations

from pathlib import Path

from texora_engine.models import (
    catalog,
    pix2tex_spec,
    pp_doclayout_spec,
    pp_ocrv5_det_spec,
    pp_ocrv5_rec_spec,
)


def test_pix2tex_spec_validates_and_composes_paths(tmp_path: Path) -> None:
    spec = pix2tex_spec(tmp_path / "models")
    assert spec.id == "pix2tex"
    assert spec.version == "v0.0.1"
    assert spec.license == "MIT"
    names = {f.name for f in spec.files}
    assert names == {"weights.pth", "image_resizer.pth"}
    # Pinned URLs are the immutable per-tag release assets.
    for f in spec.files:
        assert f.url.startswith(
            "https://github.com/lukas-blecher/LaTeX-OCR/releases/download/v0.0.1/"
        )
        assert len(f.sha256) == 64
        assert f.size > 0
    assert spec.file_path("weights.pth") == tmp_path / "models" / "pix2tex" / "weights.pth"


def test_file_path_rejects_unknown_name(tmp_path: Path) -> None:
    spec = pix2tex_spec(tmp_path / "models")
    try:
        spec.file_path("does_not_exist.pth")
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected KeyError for unknown file name")


def test_catalog_contains_pix2tex_and_m3_onnx_models(tmp_path: Path) -> None:
    cat = catalog(tmp_path / "models")
    assert set(cat) == {"pix2tex", "pp_doclayout", "pp_ocrv5_det", "pp_ocrv5_rec"}


def test_m3_onnx_specs_pin_exact_file_names_and_apache_license(tmp_path: Path) -> None:
    models = tmp_path / "models"

    doclayout = pp_doclayout_spec(models)
    assert doclayout.id == "pp_doclayout"
    assert doclayout.license == "Apache-2.0"
    assert {f.name for f in doclayout.files} == {"doclayout.onnx", "label_map.txt"}

    det = pp_ocrv5_det_spec(models)
    assert det.id == "pp_ocrv5_det"
    assert det.license == "Apache-2.0"
    assert {f.name for f in det.files} == {"det.onnx"}

    rec = pp_ocrv5_rec_spec(models)
    assert rec.id == "pp_ocrv5_rec"
    assert rec.license == "Apache-2.0"
    # rec_keys.txt is the required character dictionary (design S2.1).
    assert {f.name for f in rec.files} == {"rec.onnx", "rec_keys.txt"}

    # file_path composes under the model's target dir; an unpinned name raises KeyError loudly.
    assert doclayout.file_path("doclayout.onnx") == models / "pp_doclayout" / "doclayout.onnx"


def test_m3_onnx_specs_are_pin_on_first_fetch(tmp_path: Path) -> None:
    # URL + SHA-256 are pin-on-first-fetch placeholders at adoption (honesty note); only the
    # file-name contract is pinned now. SHA fields are still valid 64-char hex strings.
    for spec in (
        pp_doclayout_spec(tmp_path / "models"),
        pp_ocrv5_det_spec(tmp_path / "models"),
        pp_ocrv5_rec_spec(tmp_path / "models"),
    ):
        for f in spec.files:
            assert f.url == "PIN_ON_FIRST_FETCH"
            assert len(f.sha256) == 64
