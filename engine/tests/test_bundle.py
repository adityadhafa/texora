"""Offline-bundle import tests — zero network access, pinned-checksum verification."""

from __future__ import annotations

import hashlib
import socket
import zipfile
from pathlib import Path

import pytest
from texora_engine.models import (
    BundleIncomplete,
    ChecksumMismatch,
    ModelFile,
    ModelSpec,
    import_bundle,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any accidental socket connection fail loudly during bundle import."""

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("bundle import must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", _boom)


def _spec(target: Path, data: bytes) -> ModelSpec:
    sha = hashlib.sha256(data).hexdigest()
    return ModelSpec(
        id="test-model",
        version="v0",
        license="MIT",
        target_dir=target,
        files=[ModelFile(name="weights.bin", url="http://unused", sha256=sha, size=len(data))],
    )


def test_import_from_directory(tmp_path: Path) -> None:
    data = b"bundle-weights" * 50
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "weights.bin").write_bytes(data)

    spec = _spec(tmp_path / "models" / "test-model", data)
    import_bundle(spec, bundle_dir)

    assert (spec.target_dir / "weights.bin").read_bytes() == data


def test_import_from_zip(tmp_path: Path) -> None:
    data = b"zipped-weights" * 50
    zpath = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("weights.bin", data)

    spec = _spec(tmp_path / "models" / "test-model", data)
    import_bundle(spec, zpath)
    assert (spec.target_dir / "weights.bin").read_bytes() == data


def test_missing_file_rejected(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()  # empty
    spec = _spec(tmp_path / "models" / "test-model", b"data")
    with pytest.raises(BundleIncomplete):
        import_bundle(spec, bundle_dir)


def test_bad_hash_rejected(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "weights.bin").write_bytes(b"tampered")
    # Spec expects a different payload's hash.
    spec = _spec(tmp_path / "models" / "test-model", b"original-data")
    with pytest.raises(ChecksumMismatch):
        import_bundle(spec, bundle_dir)
    # Nothing promoted.
    assert not (spec.target_dir / "weights.bin").exists()
