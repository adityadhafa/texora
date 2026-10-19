"""FTS5 search tests over recognized region content (design §4.3/§4.4, R-UI-1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from texora_engine.db import fts_dao, init_db, jobs_dao, pages_dao, regions_dao
from texora_engine.db.jobs_dao import JobRow
from texora_engine.db.regions_dao import RegionInsert

_T0 = "2025-01-01T00:00:00Z"


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "texora.db")
    yield c
    c.close()


def _seed(conn: sqlite3.Connection) -> None:
    jobs_dao.create_job(
        conn,
        JobRow(
            id="j1",
            source_path="/d/j1.pdf",
            source_name="j1.pdf",
            status="done",
            options_json="{}",
            total_pages=1,
            priority=0,
            created_at=_T0,
            updated_at=_T0,
        ),
    )
    pages_dao.bulk_insert_pending(conn, "j1", [("pg0", 0)])
    regions_dao.insert_regions(
        conn,
        [
            RegionInsert(
                id="r1",
                page_id="pg0",
                type="paragraph",
                bbox_json="[0,0,1,1]",
                reading_order=0,
                content="The integral of a continuous function is well defined.",
                validation="ok",
            ),
            RegionInsert(
                id="r2",
                page_id="pg0",
                type="paragraph",
                bbox_json="[0,0,1,1]",
                reading_order=1,
                content="A derivative measures the rate of change.",
                validation="ok",
            ),
            RegionInsert(
                id="r3",
                page_id="pg0",
                type="figure",
                bbox_json="[0,0,1,1]",
                reading_order=2,
                content=None,  # NULL content is not indexed (trigger WHERE guard).
                validation="ok",
            ),
        ],
    )


def test_search_returns_expected_region_and_job(conn: sqlite3.Connection) -> None:
    _seed(conn)
    hits = fts_dao.search(conn, "integral")
    assert len(hits) == 1
    assert hits[0].region_id == "r1"
    assert hits[0].job_id == "j1"
    assert "integral" in hits[0].snippet.lower()


def test_search_null_content_not_indexed(conn: sqlite3.Connection) -> None:
    _seed(conn)
    # "figure" text only lived in the region.type, not content; the figure row has NULL content.
    assert fts_dao.search(conn, "figure") == []


def test_search_ranks_and_limits(conn: sqlite3.Connection) -> None:
    _seed(conn)
    hits = fts_dao.search(conn, "function OR change", limit=10)
    ids = {h.region_id for h in hits}
    assert ids == {"r1", "r2"}
    limited = fts_dao.search(conn, "function OR change", limit=1)
    assert len(limited) == 1


def test_region_update_refreshes_fts(conn: sqlite3.Connection) -> None:
    _seed(conn)
    with conn:
        conn.execute("UPDATE region SET content='eigenvalue decomposition' WHERE id='r1'")
    assert fts_dao.search(conn, "integral") == []
    hits = fts_dao.search(conn, "eigenvalue")
    assert [h.region_id for h in hits] == ["r1"]
