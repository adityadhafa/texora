"""SQLite data-access layer for the Texora engine (WAL mode, typed DAOs).

The job/page DAOs that collide by name with the v1 model DAO (``set_status``) are used via their
module (``jobs_dao.set_status``), not re-exported as bare names, to keep the public surface
unambiguous.
"""

from texora_engine.db.fts_dao import FtsHit, search
from texora_engine.db.jobs_dao import (
    ACTIVE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    JobRow,
    create_job,
    delete_job,
    get_job,
    list_jobs,
)
from texora_engine.db.models_dao import (
    ModelRow,
    get_model,
    set_status,
    upsert_model,
)
from texora_engine.db.pages_dao import (
    LeasedPage,
    PageCounts,
    PageRow,
    bulk_insert_pending,
    counts,
    get_page,
    lease_next,
    list_pages,
    mark_done,
    mark_failed,
    reset_failed_to_pending,
    revert_all_leased_for_active_jobs,
    revert_expired_leases,
)
from texora_engine.db.regions_dao import RegionInsert, insert_regions
from texora_engine.db.schema import SCHEMA_VERSION, connect, init_db, migrate
from texora_engine.db.settings_dao import get_setting, set_setting

__all__ = [
    "ACTIVE_JOB_STATUSES",
    "TERMINAL_JOB_STATUSES",
    "SCHEMA_VERSION",
    "FtsHit",
    "JobRow",
    "LeasedPage",
    "ModelRow",
    "PageCounts",
    "PageRow",
    "RegionInsert",
    "bulk_insert_pending",
    "connect",
    "counts",
    "create_job",
    "delete_job",
    "get_job",
    "get_model",
    "get_page",
    "get_setting",
    "init_db",
    "insert_regions",
    "lease_next",
    "list_jobs",
    "list_pages",
    "mark_done",
    "mark_failed",
    "migrate",
    "reset_failed_to_pending",
    "revert_all_leased_for_active_jobs",
    "revert_expired_leases",
    "search",
    "set_setting",
    "set_status",
    "upsert_model",
]
