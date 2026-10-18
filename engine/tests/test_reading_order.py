"""Reading-order tests: columns, equation-number binding, inline-run order, determinism."""

from __future__ import annotations

import json
from pathlib import Path

from texora_engine.layout.base import BBox, Region, RegionType
from texora_engine.layout.reading_order import order


def _load_fixture(fixtures_dir: Path, name: str) -> tuple[list[Region], list[str], int, int]:
    """Load a synthetic region fixture: (regions, id-in-input-order, width, height).

    ``id`` is a test-only label carried in parallel (it is not a Region field), so the test can
    assert the output sequence by stable ids.
    """

    data = json.loads((fixtures_dir / name).read_text(encoding="utf-8"))
    ids: list[str] = []
    regions: list[Region] = []
    for raw in data["regions"]:
        ids.append(raw["id"])
        regions.append(
            Region(
                type=RegionType(raw["type"]),
                bbox=BBox(**raw["bbox"]),
                confidence=raw["confidence"],
            )
        )
    return regions, ids, data["width"], data["height"]


def _ordered_ids(regions: list[Region], ids: list[str], ordered: list[Region]) -> list[str]:
    """Map the ordered output regions back to their input ids by identity of bbox+type."""

    # Build a lookup from a region's distinguishing key to its id.
    key_to_id: dict[tuple[object, float, float, float, float], str] = {}
    for r, i in zip(regions, ids, strict=True):
        key_to_id[(r.type, r.bbox.x0, r.bbox.y0, r.bbox.x1, r.bbox.y1)] = i
    out: list[str] = []
    for r in ordered:
        out.append(key_to_id[(r.type, r.bbox.x0, r.bbox.y0, r.bbox.x1, r.bbox.y1)])
    return out


def test_two_column_interleaved_order_and_eqnum_binding(fixtures_dir: Path) -> None:
    data = json.loads((fixtures_dir / "two_column.json").read_text(encoding="utf-8"))
    regions, ids, width, height = _load_fixture(fixtures_dir, "two_column.json")

    ordered = order(regions, width, height)

    # reading_order is set contiguously 0..n-1.
    assert [r.reading_order for r in ordered] == list(range(len(ordered)))
    assert _ordered_ids(regions, ids, ordered) == data["expected_order_ids"]


def test_eqnum_sits_immediately_after_its_display_math(fixtures_dir: Path) -> None:
    regions, ids, width, height = _load_fixture(fixtures_dir, "two_column.json")
    ordered = order(regions, width, height)
    out_ids = _ordered_ids(regions, ids, ordered)
    disp_idx = out_ids.index("L3_disp")
    assert out_ids[disp_idx + 1] == "L4_eqnum"


def test_inline_math_paragraph_runs_text_math_text(fixtures_dir: Path) -> None:
    data = json.loads((fixtures_dir / "inline_math_para.json").read_text(encoding="utf-8"))
    regions, ids, width, height = _load_fixture(fixtures_dir, "inline_math_para.json")

    ordered = order(regions, width, height)

    assert _ordered_ids(regions, ids, ordered) == data["expected_order_ids"]
    # Explicitly: the sequence is text -> math -> text.
    types = [r.type for r in ordered]
    assert types == [RegionType.PARAGRAPH, RegionType.INLINE_MATH, RegionType.PARAGRAPH]


def test_order_is_deterministic(fixtures_dir: Path) -> None:
    regions, _ids, width, height = _load_fixture(fixtures_dir, "two_column.json")
    first = [r.reading_order for r in order(list(regions), width, height)]
    second = [r.reading_order for r in order(list(regions), width, height)]
    assert first == second


def test_empty_input_returns_empty() -> None:
    assert order([], 1000, 1400) == []


def test_headers_first_footers_last() -> None:
    regions = [
        Region(type=RegionType.FOOTER, bbox=BBox(x0=0, y0=1350, x1=1000, y1=1390), confidence=0.9),
        Region(type=RegionType.PARAGRAPH, bbox=BBox(x0=40, y0=200, x1=960, y1=400), confidence=0.9),
        Region(type=RegionType.HEADER, bbox=BBox(x0=0, y0=10, x1=1000, y1=50), confidence=0.9),
    ]
    ordered = order(regions, 1000, 1400)
    assert ordered[0].type == RegionType.HEADER
    assert ordered[-1].type == RegionType.FOOTER
