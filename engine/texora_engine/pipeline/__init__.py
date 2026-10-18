"""Pipeline package: the page assembler + the typed page/document result models (M3).

Public surface re-exported here so callers import from ``texora_engine.pipeline`` without reaching
into submodules.
"""

from __future__ import annotations

from texora_engine.pipeline.assembler import PipelineDeps, assemble_page
from texora_engine.pipeline.page_result import (
    DocumentResult,
    InlineRun,
    PageResult,
    RegionContent,
    RunKind,
)

__all__ = [
    "DocumentResult",
    "InlineRun",
    "PageResult",
    "PipelineDeps",
    "RegionContent",
    "RunKind",
    "assemble_page",
]
