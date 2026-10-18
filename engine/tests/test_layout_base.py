"""Layout base-types tests: Region/LayoutResult validation + confidence bounds + Protocol shape."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from texora_engine.layout.base import (
    BBox,
    LayoutDetector,
    LayoutResult,
    Region,
    RegionType,
)


def test_region_type_has_full_taxonomy() -> None:
    expected = {
        "title",
        "paragraph",
        "inline_math",
        "display_math",
        "equation_number",
        "table",
        "figure",
        "caption",
        "footnote",
        "header",
        "footer",
        "list",
        "code",
        "handwriting",
        "unknown",
    }
    assert {rt.value for rt in RegionType} == expected


def test_bbox_derived_geometry() -> None:
    box = BBox(x0=10.0, y0=20.0, x1=110.0, y1=70.0)
    assert box.width == 100.0
    assert box.height == 50.0
    assert box.cx == 60.0
    assert box.cy == 45.0


def test_region_defaults_and_valid_confidence() -> None:
    region = Region(
        type=RegionType.PARAGRAPH,
        bbox=BBox(x0=0, y0=0, x1=10, y1=10),
        confidence=0.5,
    )
    assert region.reading_order == -1
    assert region.source == "model"


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0])
def test_region_confidence_bounds_rejected(bad: float) -> None:
    with pytest.raises(ValidationError):
        Region(type=RegionType.PARAGRAPH, bbox=BBox(x0=0, y0=0, x1=1, y1=1), confidence=bad)


def test_layout_result_round_trip() -> None:
    result = LayoutResult(
        regions=[Region(type=RegionType.TITLE, bbox=BBox(x0=0, y0=0, x1=5, y1=5), confidence=0.9)],
        engine_id="pp_doclayout_onnx",
    )
    reloaded = LayoutResult.model_validate_json(result.model_dump_json())
    assert reloaded.engine_id == "pp_doclayout_onnx"
    assert reloaded.regions[0].type == RegionType.TITLE


def test_protocol_is_runtime_checkable() -> None:
    class _Fake:
        id = "fake"
        model_ids: tuple[str, ...] = ()

        def detect(self, image: object, page: object) -> LayoutResult:  # noqa: ARG002
            return LayoutResult(regions=[], engine_id=self.id)

    assert isinstance(_Fake(), LayoutDetector)
