"""Model registry, downloader, offline-bundle import, and store."""

from texora_engine.models.bundle import import_bundle
from texora_engine.models.catalog import PIX2TEX_MODEL_ID, catalog, pix2tex_spec
from texora_engine.models.downloader import (
    download_model,
    sha256_file,
    verify_file,
)
from texora_engine.models.errors import (
    BundleIncomplete,
    ChecksumMismatch,
    ModelError,
    ModelNotReady,
)
from texora_engine.models.progress import (
    ModelDownloadState,
    ModelFileProgress,
    ModelProgress,
)
from texora_engine.models.registry import ModelFile, ModelSpec
from texora_engine.models.store import ModelStore

__all__ = [
    "PIX2TEX_MODEL_ID",
    "BundleIncomplete",
    "ChecksumMismatch",
    "ModelDownloadState",
    "ModelError",
    "ModelFile",
    "ModelFileProgress",
    "ModelNotReady",
    "ModelProgress",
    "ModelSpec",
    "ModelStore",
    "catalog",
    "download_model",
    "import_bundle",
    "pix2tex_spec",
    "sha256_file",
    "verify_file",
]
