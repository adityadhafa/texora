"""Reading-order computation — pure, deterministic XY-cut + columns (design §6.4, F7).

``order(regions, width, height)`` assigns each region a ``reading_order`` integer producing a
globally consistent top-to-bottom, left-to-right sequence that handles multi-column pages. It
takes only the page ``width``/``height`` (the fields the gutter + whitespace thresholds need), not
the whole :class:`~texora_engine.ingest.base.RenderedPage`, keeping the contract a minimal pure
function.

Two-level ordering (design §6.4/§6.5):
- **Block level** — regions are ordered as a sequence (the ``reading_order`` integer on each
  :class:`~texora_engine.layout.base.Region`).
- **Intra-block run level** — inline math *inside* a paragraph is carried by the detector's
  ``inlines`` run list (built in the born-digital / model path), already left-to-right within the
  line; the block's ``reading_order`` is the block integer and the run list order is the
  intra-block sequence. The exporter concatenates runs in list order, so inline ``$...$`` lands at
  its true position in the paragraph's flow.

Special handling:
- **Columns** — region x-centers are projected onto the x-axis; vertical gutters (empty x-bands
  wider than a ``width``-relative threshold) split the page into N columns.
- **Recursive XY-cut** — within a column (or the whole page when single-column) regions are
  ordered by the widest alternating horizontal/vertical whitespace gaps.
- **Equation numbers** — a right-margin :attr:`RegionType.EQUATION_NUMBER` attaches to the nearest
  :attr:`RegionType.DISPLAY_MATH` on the same horizontal band and is ordered immediately after it.
- **Headers/footers** — ordered out-of-band: headers first, footers last.

Deterministic: ties break on ``(y0, x0)`` so the same input always yields the same order.
"""

from __future__ import annotations

from texora_engine.layout.base import Region, RegionType

# A vertical gutter wider than this fraction of page width splits columns.
_COLUMN_GUTTER_FRAC = 0.06
# Two regions are on the same horizontal band if their y-centers are within this fraction of
# page height.
_SAME_BAND_FRAC = 0.04


def _detect_columns(regions: list[Region], width: int) -> list[list[Region]]:
    """Split ``regions`` into columns by vertical gutters in the x-center projection.

    Returns a left-to-right list of column region-groups. A single column when no gutter wider
    than the threshold is found.
    """

    if not regions or width <= 0:
        return [regions]

    gutter = width * _COLUMN_GUTTER_FRAC
    # Sort region x-intervals by left edge and find gaps between consecutive covered x-ranges.
    intervals = sorted(((r.bbox.x0, r.bbox.x1) for r in regions), key=lambda iv: iv[0])
    boundaries: list[float] = []
    cur_right = intervals[0][1]
    for left, right in intervals[1:]:
        if left - cur_right > gutter:
            boundaries.append((cur_right + left) / 2.0)
        cur_right = max(cur_right, right)

    if not boundaries:
        return [regions]

    columns: list[list[Region]] = [[] for _ in range(len(boundaries) + 1)]
    for r in regions:
        col_idx = 0
        for b in boundaries:
            if r.bbox.cx > b:
                col_idx += 1
            else:
                break
        columns[col_idx].append(r)
    return [c for c in columns if c]


def _xy_cut(regions: list[Region], width: int, height: int) -> list[Region]:
    """Recursive XY-cut: order ``regions`` top-to-bottom then left-to-right by whitespace gaps.

    Alternates horizontal and vertical cuts on the widest whitespace gap. Terminates when a group
    has <= 1 region or no cut is found; the base case orders by ``(y0, x0)``.
    """

    def _cut(group: list[Region], horizontal: bool) -> list[Region]:
        if len(group) <= 1:
            return list(group)

        # Try a cut along the requested axis on the widest inter-region whitespace gap.
        if horizontal:
            spans = sorted(((r.bbox.y0, r.bbox.y1, r) for r in group), key=lambda t: t[0])
        else:
            spans = sorted(((r.bbox.x0, r.bbox.x1, r) for r in group), key=lambda t: t[0])

        best_gap = 0.0
        best_at = -1
        cur_end = spans[0][1]
        for i in range(1, len(spans)):
            start = spans[i][0]
            gap = start - cur_end
            if gap > best_gap:
                best_gap = gap
                best_at = i
            cur_end = max(cur_end, spans[i][1])

        min_gap = (height if horizontal else width) * 0.01
        if best_at == -1 or best_gap <= min_gap:
            # No usable cut on this axis: try the other axis, else settle on (y0, x0).
            if horizontal:
                return _cut(group, horizontal=False)
            return sorted(group, key=lambda r: (r.bbox.y0, r.bbox.x0))

        first = [t[2] for t in spans[:best_at]]
        second = [t[2] for t in spans[best_at:]]
        # Recurse alternating the axis; first block (top/left) precedes the second.
        return _cut(first, not horizontal) + _cut(second, not horizontal)

    return _cut(list(regions), horizontal=True)


def _bind_equation_numbers(ordered: list[Region], height: int) -> list[Region]:
    """Move each right-margin EQUATION_NUMBER to sit immediately after its display equation.

    An equation number binds to the nearest DISPLAY_MATH that is on the same horizontal band and
    sits to its left (the number is in the right margin *of its equation's band*, which works for
    both single- and multi-column pages — the absolute page x of a right-margin number is small in
    a left column). Numbers with no display-math match keep their XY-cut position.
    """

    same_band = height * _SAME_BAND_FRAC if height > 0 else 0.0
    eq_numbers = [r for r in ordered if r.type == RegionType.EQUATION_NUMBER]
    if not eq_numbers:
        return ordered

    remaining = [r for r in ordered if r not in eq_numbers]
    result: list[Region] = []
    for r in remaining:
        result.append(r)
        if r.type == RegionType.DISPLAY_MATH:
            # Attach the nearest unbound equation number on the same band that sits to the right.
            candidates = [
                en
                for en in eq_numbers
                if en.bbox.cx >= r.bbox.cx
                and abs(en.bbox.cy - r.bbox.cy) <= max(same_band, r.bbox.height)
            ]
            if candidates:
                nearest = min(candidates, key=lambda en: abs(en.bbox.cy - r.bbox.cy))
                result.append(nearest)
                eq_numbers.remove(nearest)

    # Any equation number that found no display-math partner keeps the flow (appended in order).
    result.extend(eq_numbers)
    return result


def order(regions: list[Region], width: int, height: int) -> list[Region]:
    """Assign ``reading_order`` to each region and return them in reading order.

    Pure and deterministic. Headers are emitted first and footers last (out-of-band); the body is
    column-split then XY-cut, and right-margin equation numbers bind to their display equations.
    The input list is not mutated; new :class:`Region` copies carry the ``reading_order`` index.
    """

    if not regions:
        return []

    headers = [r for r in regions if r.type == RegionType.HEADER]
    footers = [r for r in regions if r.type == RegionType.FOOTER]
    body = [r for r in regions if r.type not in {RegionType.HEADER, RegionType.FOOTER}]

    headers_sorted = sorted(headers, key=lambda r: (r.bbox.y0, r.bbox.x0))
    footers_sorted = sorted(footers, key=lambda r: (r.bbox.y0, r.bbox.x0))

    ordered_body: list[Region] = []
    for column in _detect_columns(body, width):
        ordered_body.extend(_xy_cut(column, width, height))

    ordered_body = _bind_equation_numbers(ordered_body, height)

    sequence = headers_sorted + ordered_body + footers_sorted
    return [r.model_copy(update={"reading_order": i}) for i, r in enumerate(sequence)]
