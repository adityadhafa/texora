"""Typed errors for the model registry / downloader / bundle paths."""

from __future__ import annotations


class ModelError(Exception):
    """Base class for model-registry errors."""


class ChecksumMismatch(ModelError):
    """A downloaded/imported file's SHA-256 did not match the pinned value."""

    def __init__(self, name: str, expected: str, actual: str) -> None:
        self.name = name
        self.expected = expected
        self.actual = actual
        # Only the short prefixes are logged/surfaced — never full byte content.
        super().__init__(
            f"checksum mismatch for {name!r}: " f"expected {expected[:12]}…, got {actual[:12]}…"
        )


class ModelNotReady(ModelError):
    """A model was requested but is not in the `ready` state (needs download)."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        super().__init__(f"model {model_id!r} is not ready; download it first")


class BundleIncomplete(ModelError):
    """An offline bundle is missing one or more required files."""

    def __init__(self, model_id: str, missing: list[str]) -> None:
        self.model_id = model_id
        self.missing = missing
        super().__init__(f"bundle for {model_id!r} missing files: {missing}")
