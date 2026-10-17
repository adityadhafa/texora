"""Offline-bundle import — install model files from a local dir/zip with no network.

Each file is verified against the SAME pinned SHA-256 as the downloader (via the shared
:func:`verify_file`) before being promoted into the model's ``target_dir``. Missing files
raise :class:`BundleIncomplete`; a bad hash raises :class:`ChecksumMismatch`. No network
access happens here.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from texora_engine.logging_config import get_logger
from texora_engine.models.downloader import verify_file
from texora_engine.models.errors import BundleIncomplete
from texora_engine.models.registry import ModelSpec

logger = get_logger("models.bundle")


def _resolve_source_dir(source: Path, stack: list[Path]) -> Path:
    """Return a directory containing the bundle files.

    If ``source`` is a zip archive it is extracted to a temp dir (tracked in ``stack`` for
    cleanup); if it is already a directory it is returned as-is.
    """

    if source.is_dir():
        return source
    if zipfile.is_zipfile(source):
        tmp = Path(tempfile.mkdtemp(prefix="texora_bundle_"))
        stack.append(tmp)
        with zipfile.ZipFile(source) as zf:
            zf.extractall(tmp)
        return tmp
    raise BundleIncomplete("<bundle>", [str(source)])


def import_bundle(spec: ModelSpec, source: Path) -> None:
    """Import ``spec``'s files from ``source`` (a directory or zip), verifying each.

    The bundle may nest the files at its root or under a single top-level folder; both are
    searched. Files are only promoted after a successful checksum verification.
    """

    cleanup: list[Path] = []
    try:
        src_dir = _resolve_source_dir(source, cleanup)

        # Locate each expected file (root first, then one level of subdirs).
        resolved: dict[str, Path] = {}
        missing: list[str] = []
        for file in spec.files:
            candidate = src_dir / file.name
            if not candidate.exists():
                nested = list(src_dir.glob(f"*/{file.name}"))
                candidate = nested[0] if nested else candidate
            if candidate.exists():
                resolved[file.name] = candidate
            else:
                missing.append(file.name)
        if missing:
            raise BundleIncomplete(spec.id, missing)

        # Verify every file BEFORE promoting any (all-or-nothing integrity).
        for file in spec.files:
            verify_file(resolved[file.name], file)

        spec.target_dir.mkdir(parents=True, exist_ok=True)
        for file in spec.files:
            dst = spec.target_dir / file.name
            shutil.copyfile(resolved[file.name], dst)
            logger.info("imported %s/%s from bundle", spec.id, file.name)
    finally:
        for tmp in cleanup:
            shutil.rmtree(tmp, ignore_errors=True)
