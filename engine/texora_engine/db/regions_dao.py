"""Typed data-access helpers for the ``region`` table (design §4.3).

Inserting regions populates the FTS5 index automatically via the ``region_ai`` trigger — callers
never touch ``region_fts`` directly. Regions carry the per-region recognized ``content`` (text or
latex) that feeds the Library full-text search (R-UI-1).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class RegionInsert:
    """A region to persist for a page (design §4.2 ``region`` columns)."""

    id: str
    page_id: str
    type: str
    bbox_json: str
    reading_order: int
    det_confidence: float | None = None
    content: str | None = None
    rec_confidence: float | None = None
    validation: str | None = None


def insert_regions(conn: sqlite3.Connection, regions: list[RegionInsert]) -> None:
    """Insert a page's regions in ONE transaction (FTS filled by the ``region_ai`` trigger)."""

    with conn:
        conn.executemany(
            """
            INSERT INTO region (
                id, page_id, type, bbox_json, det_confidence,
                reading_order, content, rec_confidence, validation
            ) VALUES (
                :id, :page_id, :type, :bbox_json, :det_confidence,
                :reading_order, :content, :rec_confidence, :validation
            )
            """,
            [
                {
                    "id": r.id,
                    "page_id": r.page_id,
                    "type": r.type,
                    "bbox_json": r.bbox_json,
                    "det_confidence": r.det_confidence,
                    "reading_order": r.reading_order,
                    "content": r.content,
                    "rec_confidence": r.rec_confidence,
                    "validation": r.validation,
                }
                for r in regions
            ],
        )
