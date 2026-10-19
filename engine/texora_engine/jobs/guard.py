"""Per-page failure-isolation helpers (design §5, R-JOB-6/R-SEC-3).

Two guards keep a hostile page from killing a job:

* a **resource guard** that rejects a rendered page whose pixel area exceeds ``max_snip_pixels``
  (the existing decompression-bomb bound; ``Image.MAX_IMAGE_PIXELS`` is set globally in ``app.py``);
* a **per-page wall-clock timeout** applied by the runner via ``asyncio.wait_for`` around the whole
  ``assemble_page`` offload.

Both mark the single page ``failed`` and let the loop continue — a failed page never kills the job.
"""

from __future__ import annotations

from texora_engine.ingest.base import RenderedPage


class PageResourceError(Exception):
    """A rendered page exceeds a resource bound (area/decompression-bomb guard)."""


def check_page_resources(rendered: RenderedPage, max_pixels: int) -> None:
    """Raise :class:`PageResourceError` when the rendered page's pixel area is over bound.

    Mirrors the M2 snip-area guard (``settings.max_snip_pixels``) so a decompression-bomb-sized
    page is isolated to a failed page rather than exhausting memory on the whole job.
    """

    area = rendered.width * rendered.height
    if area > max_pixels:
        raise PageResourceError(
            f"page area {rendered.width}x{rendered.height}={area}px exceeds {max_pixels}px bound"
        )
