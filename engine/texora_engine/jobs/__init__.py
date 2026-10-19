"""Job scheduling package (M4): streaming runner, lease loop, checkpoint/resume, export writer.

All M4 scheduling logic lives here. The UI and API never depend on a specific engine; they drive
the :class:`~texora_engine.jobs.manager.JobManager`, which schedules the reused M3
``assemble_page`` per page with bounded concurrency and per-page SQLite checkpointing.
"""

from texora_engine.jobs.manager import JobManager
from texora_engine.jobs.models import JobOptions, JobProgress, ProgressEvent

__all__ = [
    "JobManager",
    "JobOptions",
    "JobProgress",
    "ProgressEvent",
]
