"""Tests for the ``page`` lease state machine DAO (design §3.2, §4.3, §4.4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from texora_engine.db import init_db, jobs_dao, pages_dao
from texora_engine.db.jobs_dao import JobRow

_T0 = "2025-01-01T00:00:00Z"


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "texora.db")
    yield c
    c.close()


def _mk_job(conn: sqlite3.Connection, job_id: str, *, status: str, n_pages: int) -> None:
    jobs_dao.create_job(
        conn,
        JobRow(
            id=job_id,
            source_path=f"/d/{job_id}.pdf",
            source_name=f"{job_id}.pdf",
            status=status,
            options_json="{}",
            total_pages=n_pages,
            priority=0,
            created_at=_T0,
            updated_at=_T0,
        ),
    )
    pages_dao.bulk_insert_pending(conn, job_id, [(f"{job_id}-p{i}", i) for i in range(n_pages)])


def test_lease_next_in_index_order_then_none(conn: sqlite3.Connection) -> None:
    _mk_job(conn, "j", status="running", n_pages=3)
    leased = [pages_dao.lease_next(conn, "j", f"tok{i}", "2099-01-01T00:00:00Z") for i in range(3)]
    assert [p.page_index for p in leased if p] == [0, 1, 2]
    assert pages_dao.lease_next(conn, "j", "tok3", "2099-01-01T00:00:00Z") is None


def test_lease_next_atomic_two_attempts_distinct_pages(conn: sqlite3.Connection) -> None:
    _mk_job(conn, "j", status="running", n_pages=2)
    a = pages_dao.lease_next(conn, "j", "a", "2099-01-01T00:00:00Z")
    b = pages_dao.lease_next(conn, "j", "b", "2099-01-01T00:00:00Z")
    assert a is not None and b is not None
    assert a.id != b.id
    assert {a.page_index, b.page_index} == {0, 1}


def test_mark_done_token_guarded(conn: sqlite3.Connection) -> None:
    _mk_job(conn, "j", status="running", n_pages=1)
    leased = pages_dao.lease_next(conn, "j", "good", "2099-01-01T00:00:00Z")
    assert leased is not None
    # A stale token cannot commit.
    assert (
        pages_dao.mark_done(
            conn,
            leased.id,
            "stale",
            rollup_status="ok",
            result_json="{}",
            avg_confidence=0.9,
            finished_at=_T0,
        )
        is False
    )
    # The real owner can.
    assert (
        pages_dao.mark_done(
            conn,
            leased.id,
            "good",
            rollup_status="ok",
            result_json="{}",
            avg_confidence=0.9,
            finished_at=_T0,
        )
        is True
    )
    assert pages_dao.counts(conn, "j").done == 1


def test_mark_failed_sets_rollup_failed(conn: sqlite3.Connection) -> None:
    _mk_job(conn, "j", status="running", n_pages=1)
    leased = pages_dao.lease_next(conn, "j", "t", "2099-01-01T00:00:00Z")
    assert leased is not None
    assert pages_dao.mark_failed(conn, leased.id, "t", error="boom", finished_at=_T0) is True
    page = pages_dao.get_page(conn, leased.id)
    assert page is not None
    assert page.status == "failed"
    assert page.rollup_status == "failed"
    assert page.error == "boom"


def test_revert_expired_leases_only_expired(conn: sqlite3.Connection) -> None:
    _mk_job(conn, "j", status="running", n_pages=2)
    expired = pages_dao.lease_next(conn, "j", "e", "2000-01-01T00:00:00Z")
    fresh = pages_dao.lease_next(conn, "j", "f", "2099-01-01T00:00:00Z")
    assert expired is not None and fresh is not None
    reverted = pages_dao.revert_expired_leases(conn, "2025-06-01T00:00:00Z")
    assert reverted == 1
    assert pages_dao.get_page(conn, expired.id).status == "pending"
    assert pages_dao.get_page(conn, fresh.id).status == "leased"


def test_revert_all_leased_for_active_jobs_ignores_ttl_and_terminal(
    conn: sqlite3.Connection,
) -> None:
    _mk_job(conn, "active", status="running", n_pages=1)
    _mk_job(conn, "donejob", status="done", n_pages=1)
    # Both leased with a FUTURE expiry — the TTL sweeper would not touch them.
    active_leased = pages_dao.lease_next(conn, "active", "a", "2099-01-01T00:00:00Z")
    terminal_leased = pages_dao.lease_next(conn, "donejob", "d", "2099-01-01T00:00:00Z")
    assert active_leased is not None and terminal_leased is not None

    reverted = pages_dao.revert_all_leased_for_active_jobs(conn)
    assert reverted == 1
    # The active job's leased page is reverted unconditionally (despite the future TTL).
    assert pages_dao.get_page(conn, active_leased.id).status == "pending"
    # The terminal (done) job's leased page is left untouched.
    assert pages_dao.get_page(conn, terminal_leased.id).status == "leased"


def test_reset_failed_to_pending_only_failed(conn: sqlite3.Connection) -> None:
    _mk_job(conn, "j", status="running", n_pages=2)
    done = pages_dao.lease_next(conn, "j", "a", "2099-01-01T00:00:00Z")
    failed = pages_dao.lease_next(conn, "j", "b", "2099-01-01T00:00:00Z")
    assert done is not None and failed is not None
    pages_dao.mark_done(
        conn,
        done.id,
        "a",
        rollup_status="ok",
        result_json="{}",
        avg_confidence=0.9,
        finished_at=_T0,
    )
    pages_dao.mark_failed(conn, failed.id, "b", error="x", finished_at=_T0)

    reset = pages_dao.reset_failed_to_pending(conn, "j")
    assert reset == 1
    assert pages_dao.get_page(conn, failed.id).status == "pending"
    assert pages_dao.get_page(conn, failed.id).error is None
    # The failed row kept its attempts count (1 lease so far).
    assert pages_dao.get_page(conn, failed.id).attempts == 1
    # The done row is untouched.
    assert pages_dao.get_page(conn, done.id).status == "done"


def test_counts_rolls_up_needs_review(conn: sqlite3.Connection) -> None:
    _mk_job(conn, "j", status="running", n_pages=3)
    p0 = pages_dao.lease_next(conn, "j", "a", "2099-01-01T00:00:00Z")
    p1 = pages_dao.lease_next(conn, "j", "b", "2099-01-01T00:00:00Z")
    assert p0 is not None and p1 is not None
    pages_dao.mark_done(
        conn, p0.id, "a", rollup_status="ok", result_json="{}", avg_confidence=0.9, finished_at=_T0
    )
    pages_dao.mark_done(
        conn,
        p1.id,
        "b",
        rollup_status="needs_review",
        result_json="{}",
        avg_confidence=0.5,
        finished_at=_T0,
    )
    c = pages_dao.counts(conn, "j")
    assert c.total == 3
    assert c.done == 2
    assert c.pending == 1
    assert c.needs_review == 1
