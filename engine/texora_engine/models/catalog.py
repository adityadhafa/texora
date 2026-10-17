"""Pinned model catalog.

The single source of truth for which models Texora ships with and the exact bytes it
expects. M2 pins one model: the pix2tex (LaTeX-OCR) weights.

Pin-on-first-fetch honesty note (R-INST-2/3, see docs/LICENSES.md + docs/m2-verification.md):
upstream publishes no vendor-signed checksum for these release assets. The SHA-256 values
below are **our** hashes of the upstream assets at release tag ``v0.0.1``, computed once on
first fetch and baked in here. They guarantee integrity/immutability relative to the bytes
we first pinned (tamper/corruption detection on every later fetch + offline import); they
are not an upstream attestation. A vendor-pinned / content-addressed hash is an M7 option.
"""

from __future__ import annotations

from pathlib import Path

from texora_engine.models.registry import ModelFile, ModelSpec

# pix2tex default-model id, referenced by the adapter (`model_ids`) and pipeline factory.
PIX2TEX_MODEL_ID = "pix2tex"

# Upstream GitHub release tag hosting the weight assets on lukas-blecher/LaTeX-OCR.
_PIX2TEX_TAG = "v0.0.1"
_PIX2TEX_BASE = f"https://github.com/lukas-blecher/LaTeX-OCR/releases/download/{_PIX2TEX_TAG}"

# Real values computed on this host from the pinned release assets (see adoption note above).
_PIX2TEX_FILES = [
    ModelFile(
        name="weights.pth",
        url=f"{_PIX2TEX_BASE}/weights.pth",
        sha256="a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa",
        size=102113875,
    ),
    ModelFile(
        name="image_resizer.pth",
        url=f"{_PIX2TEX_BASE}/image_resizer.pth",
        sha256="1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458",
        size=19441973,
    ),
]


def pix2tex_spec(models_dir: Path) -> ModelSpec:
    """Return the pinned pix2tex :class:`ModelSpec` rooted under ``models_dir``."""

    return ModelSpec(
        id=PIX2TEX_MODEL_ID,
        version=_PIX2TEX_TAG,
        license="MIT",
        target_dir=models_dir / PIX2TEX_MODEL_ID,
        files=list(_PIX2TEX_FILES),
    )


def catalog(models_dir: Path) -> dict[str, ModelSpec]:
    """Return the full pinned catalog keyed by model id."""

    return {PIX2TEX_MODEL_ID: pix2tex_spec(models_dir)}
