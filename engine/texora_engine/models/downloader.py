"""Checksum-verifying model downloader.

Streams each :class:`ModelFile` to a ``.incoming/<name>.part`` temp file while hashing with
SHA-256, enforces connect/read timeouts and a max-size guard, and on completion compares
the digest to the pinned value. A mismatch deletes the temp and raises
:class:`ChecksumMismatch`; a match atomically moves the file into place. Progress is
reported through an optional callback so the API/supervisor can surface byte counts.

Network egress happens ONLY here (and in nothing pix2tex does itself — the adapter is wired
to local weights only). This is the engine's single default egress path.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path

import httpx

from texora_engine.logging_config import get_logger
from texora_engine.models.errors import ChecksumMismatch
from texora_engine.models.progress import (
    ModelDownloadState,
    ModelFileProgress,
    ModelProgress,
)
from texora_engine.models.registry import ModelFile, ModelSpec

logger = get_logger("models.downloader")

# A hard ceiling so a hostile/truncated server cannot stream unbounded bytes. The pinned
# pix2tex weights are ~102 MB; 1 GiB leaves generous headroom for any single M2 asset.
MAX_FILE_BYTES = 1024 * 1024 * 1024

# httpx timeout: generous read window for large weight files, short connect.
_TIMEOUT = httpx.Timeout(connect=15.0, read=60.0, write=60.0, pool=15.0)

ProgressCallback = Callable[[ModelProgress], None]


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Compute the lowercase-hex SHA-256 of a file by streaming it."""

    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: Path, expected: ModelFile) -> None:
    """Verify ``path`` against the pinned SHA-256; raise on mismatch.

    Shared by the downloader and the offline-bundle import so both enforce the exact same
    integrity check.
    """

    actual = sha256_file(path)
    if actual != expected.sha256:
        raise ChecksumMismatch(expected.name, expected.sha256, actual)


def _emit(cb: ProgressCallback | None, progress: ModelProgress) -> None:
    if cb is not None:
        cb(progress)


def _build_progress(
    model_id: str,
    state: ModelDownloadState,
    per_file: dict[str, ModelFileProgress],
    detail: str | None = None,
) -> ModelProgress:
    files = list(per_file.values())
    return ModelProgress(
        id=model_id,
        state=state,
        bytes_received=sum(f.received for f in files),
        bytes_total=sum(f.total for f in files),
        files=files,
        detail=detail,
    )


def download_model(spec: ModelSpec, on_progress: ProgressCallback | None = None) -> None:
    """Download and verify every file of ``spec`` into ``spec.target_dir``.

    Raises :class:`ChecksumMismatch` (after deleting the offending ``.part``) when a file's
    bytes do not match the pinned SHA-256. Re-downloads are safe: each attempt writes to a
    fresh ``.part`` and only atomically replaces the final file on a verified match.
    """

    target = spec.target_dir
    incoming = target / ".incoming"
    incoming.mkdir(parents=True, exist_ok=True)

    per_file: dict[str, ModelFileProgress] = {
        f.name: ModelFileProgress(name=f.name, received=0, total=f.size) for f in spec.files
    }

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for file in spec.files:
            part = incoming / f"{file.name}.part"
            digest = hashlib.sha256()
            received = 0
            logger.info("downloading %s/%s", spec.id, file.name)
            with client.stream("GET", file.url) as resp:
                resp.raise_for_status()
                with open(part, "wb") as out:
                    for chunk in resp.iter_bytes(chunk_size=1 << 20):
                        received += len(chunk)
                        if received > MAX_FILE_BYTES:
                            out.close()
                            part.unlink(missing_ok=True)
                            raise ValueError(
                                f"{file.name} exceeded max download size {MAX_FILE_BYTES} bytes"
                            )
                        out.write(chunk)
                        digest.update(chunk)
                        per_file[file.name] = ModelFileProgress(
                            name=file.name, received=received, total=file.size
                        )
                        _emit(
                            on_progress,
                            _build_progress(spec.id, ModelDownloadState.DOWNLOADING, per_file),
                        )

            # Verify the fully-received file before promoting it.
            _emit(on_progress, _build_progress(spec.id, ModelDownloadState.VERIFYING, per_file))
            actual = digest.hexdigest()
            if actual != file.sha256:
                part.unlink(missing_ok=True)
                raise ChecksumMismatch(file.name, file.sha256, actual)

            # Atomic promote into place.
            final = target / file.name
            os.replace(part, final)
            logger.info("verified + installed %s/%s", spec.id, file.name)

    _emit(on_progress, _build_progress(spec.id, ModelDownloadState.READY, per_file))
