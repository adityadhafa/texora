"""Model registry types.

A :class:`ModelSpec` pins everything needed to fetch, verify, and locate a model's files:
a stable ``id``, a ``version`` (the upstream release tag), the ``license``, an on-disk
``target_dir``, and one or more :class:`ModelFile` entries carrying the immutable source
URL, the pinned SHA-256, and the expected byte size. These are plain Pydantic models so the
pinned catalog is declarative (no magic constants scattered in code).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class ModelFile(BaseModel):
    """One downloadable file belonging to a model."""

    name: str = Field(description="On-disk filename, e.g. 'weights.pth'.")
    url: str = Field(description="Direct, immutable, non-redirecting source URL.")
    sha256: str = Field(description="Pinned lowercase hex SHA-256 of the file's bytes.")
    size: int = Field(ge=0, description="Expected size in bytes (0 if unknown).")


class ModelSpec(BaseModel):
    """A pinned model: its identity, license, files, and target directory."""

    id: str = Field(description="Stable model id used by adapters and the registry.")
    version: str = Field(description="Upstream version/tag the files were pinned from.")
    license: str = Field(description="SPDX-ish license string for docs/LICENSES.md.")
    target_dir: Path = Field(description="Directory the files are installed into.")
    files: list[ModelFile] = Field(min_length=1, description="Files that make up the model.")

    def file_path(self, name: str) -> Path:
        """Return the resolved on-disk path for the file named ``name``.

        Raises ``KeyError`` if no file with that name is pinned, so a typo surfaces loudly
        rather than returning a path to a non-existent file.
        """

        for f in self.files:
            if f.name == name:
                return self.target_dir / f.name
        raise KeyError(f"model {self.id!r} has no file named {name!r}")
