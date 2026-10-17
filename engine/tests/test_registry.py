"""Model registry + catalog tests."""

from __future__ import annotations

from pathlib import Path

from texora_engine.models import catalog, pix2tex_spec


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


def test_catalog_contains_pix2tex(tmp_path: Path) -> None:
    cat = catalog(tmp_path / "models")
    assert set(cat) == {"pix2tex"}
