"""Watch-folder intake (design §8, R-JOB-7) — watchdog Observer + settle/debounce wrapper.

When ``settings.watch_dir`` is set, ``app.py`` starts a watchdog ``Observer`` on it. A new/renamed
file event triggers a settle check (wait ``watch_settle_s``, confirm the file size is stable),
validates the extension + path, and enqueues a job. An in-memory already-enqueued set (keyed by
resolved path + mtime) de-dupes the multiple OS events one write emits. The Observer thread only
marshals enqueue work onto the engine's asyncio loop via ``loop.call_soon_threadsafe`` so all job
creation goes through the single :class:`JobManager` (no second writer — design §1 M4-ADR-1).
"""

from __future__ import annotations

import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from texora_engine.jobs.manager import JobError, JobManager
from texora_engine.jobs.models import JobOptions
from texora_engine.jobs.paths import PathValidationError, is_supported_file, validate_source_path
from texora_engine.logging_config import get_logger

logger = get_logger("jobs.watch")


class WatchFolderIngest:
    """Settle + validate + de-dupe + enqueue a watched file (thread-marshalled to the loop)."""

    def __init__(self, manager: JobManager, options: JobOptions | None = None) -> None:
        self._manager = manager
        self._options = options or JobOptions()
        self._settle_s = manager.settings.watch_settle_s
        self._seen: set[tuple[str, int]] = set()

    def _settle(self, path: Path) -> int | None:
        """Wait the settle period and confirm the size is stable; return the stable size or None."""

        try:
            first = path.stat().st_size
        except OSError:
            return None
        time.sleep(self._settle_s)
        try:
            second = path.stat().st_size
        except OSError:
            return None
        return second if first == second else None

    def process_candidate(self, raw_path: str) -> str | None:
        """Settle + validate + de-dupe + enqueue one candidate file. Returns the new job id or None.

        Deterministic given a fully-written file (no live FS race), so it is unit-testable.
        """

        try:
            resolved = validate_source_path(raw_path)
        except PathValidationError as exc:
            logger.info("watch: skipping %s: %s", raw_path, exc)
            return None
        size = self._settle(resolved)
        if size is None:
            logger.info("watch: %s not size-stable yet, skipping", resolved)
            return None
        try:
            mtime = int(resolved.stat().st_mtime)
        except OSError:
            return None
        key = (str(resolved), mtime)
        if key in self._seen:
            logger.debug("watch: already enqueued %s (mtime %d)", resolved, mtime)
            return None
        self._seen.add(key)
        try:
            job = self._manager.create_job(str(resolved), resolved.name, self._options)
        except JobError as exc:
            logger.warning("watch: could not enqueue %s: %s", resolved, exc)
            self._seen.discard(key)
            return None
        logger.info("watch: enqueued job %s for %s", job.id, resolved)
        return job.id


class _WatchHandler(FileSystemEventHandler):
    """Marshals created/moved file events onto the engine loop via call_soon_threadsafe."""

    def __init__(self, ingest: WatchFolderIngest, loop: object) -> None:
        self._ingest = ingest
        self._loop = loop

    def _submit(self, raw_path: str) -> None:
        path = Path(raw_path)
        if not is_supported_file(path):
            return
        # Run the (blocking) settle + enqueue on the loop's executor so the Observer thread never
        # touches the DB directly (single-writer discipline).
        self._loop.call_soon_threadsafe(  # type: ignore[attr-defined]
            lambda: self._loop.run_in_executor(None, self._ingest.process_candidate, raw_path)  # type: ignore[attr-defined]
        )

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._submit(str(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        dest = getattr(event, "dest_path", None)
        if dest and not event.is_directory:
            self._submit(str(dest))


def start_watch_observer(manager: JobManager, watch_dir: Path, loop: object) -> BaseObserver:
    """Start a watchdog Observer on ``watch_dir`` and return it (caller stops it on shutdown)."""

    ingest = WatchFolderIngest(manager)
    handler = _WatchHandler(ingest, loop)
    observer: BaseObserver = Observer()
    observer.schedule(handler, str(watch_dir), recursive=False)  # type: ignore[no-untyped-call]
    observer.start()  # type: ignore[no-untyped-call]
    logger.info("watch-folder observer started on %s", watch_dir)
    return observer
