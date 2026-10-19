"""Full-text search over recognized region content via the FTS5 ``region_fts`` table (R-UI-1).

The query string is always bound as a parameter to ``MATCH`` — no SQL is built by string
interpolation (design §10). Results expose the UNINDEXED ``region_id``/``job_id`` columns plus a
``snippet()`` and the ``bm25()`` rank, and NEVER the implicit FTS ``rowid`` (design §4.3, NIT-5).
"""

from __future__ import annotations

import sqlite3

from pydantic import BaseModel, Field


class FtsHit(BaseModel):
    """One ranked full-text search hit (never exposes the implicit FTS rowid)."""

    region_id: str
    job_id: str
    snippet: str
    score: float = Field(description="bm25() rank; lower is a better match.")


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[FtsHit]:
    """Return ranked FTS hits for ``query`` (bound parameter), best match first.

    ``bm25()`` returns a score where a more-negative value is a better match, so results are
    ordered ascending by ``bm25()``.
    """

    rows = conn.execute(
        """
        SELECT
            region_id AS region_id,
            job_id    AS job_id,
            snippet(region_fts, 0, '[', ']', ' … ', 16) AS snippet,
            bm25(region_fts) AS score
        FROM region_fts
        WHERE region_fts MATCH :q
        ORDER BY bm25(region_fts)
        LIMIT :limit OFFSET :offset
        """,
        {"q": query, "limit": limit, "offset": offset},
    ).fetchall()
    return [
        FtsHit(
            region_id=row["region_id"],
            job_id=row["job_id"],
            snippet=row["snippet"],
            score=float(row["score"]),
        )
        for row in rows
    ]
