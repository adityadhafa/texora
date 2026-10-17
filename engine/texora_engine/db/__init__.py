"""SQLite data-access layer for the Texora engine (WAL mode, typed DAOs)."""

from texora_engine.db.models_dao import (
    ModelRow,
    get_model,
    set_status,
    upsert_model,
)
from texora_engine.db.schema import SCHEMA_VERSION, connect, init_db, migrate
from texora_engine.db.settings_dao import get_setting, set_setting

__all__ = [
    "SCHEMA_VERSION",
    "ModelRow",
    "connect",
    "get_model",
    "get_setting",
    "init_db",
    "migrate",
    "set_setting",
    "set_status",
    "upsert_model",
]
