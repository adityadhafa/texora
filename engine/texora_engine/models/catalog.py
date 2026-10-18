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

# --- M3 ONNX model ids (layout + text), referenced by the layout/text adapters + factories.
PP_DOCLAYOUT_MODEL_ID = "pp_doclayout"
PP_OCRV5_DET_MODEL_ID = "pp_ocrv5_det"
PP_OCRV5_REC_MODEL_ID = "pp_ocrv5_rec"

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


# --- M3 ONNX models (PP-DocLayout layout + PP-OCRv5 text det/rec) ----------------------------
#
# URL + SHA-256 are PIN-ON-FIRST-FETCH at adoption, exactly like the pix2tex honesty note above:
# the exact ONNX export artifacts are selected and hashed when the model path is first wired up
# (M3 text/layout adapter features + M7 benchmark-chosen defaults). ONLY the ``ModelFile.name``s
# below are a hard contract now — they are the ``spec.file_path(name)`` keys the layout/text
# adapters request (design §2.1); the adapters KeyError loudly on an unpinned name.
#
# Provenance: these ONNX weights are exported from the official Apache-2.0 PaddleOCR/PaddleX
# releases. If a stable official ONNX export URL cannot be confirmed at adoption, the catalog
# pins the Apache-2.0 ``rapid-layout`` / ``rapidocr-onnxruntime`` redistribution of the same
# PP model family (versioned release assets, identical file-name contract) — a documented
# contingency recorded in docs/LICENSES.md, never a silent fallback. Either way the license is
# Apache-2.0 and the bytes are pinned on first fetch.
#
# ``version`` is "unpinned" until the adoption fetch stamps the real upstream tag; ``url``/
# ``sha256``/``size`` carry explicit pin-on-first-fetch placeholders so an accidental download
# attempt fails loudly rather than fetching unverified bytes.
_PIN_ON_FIRST_FETCH_URL = "PIN_ON_FIRST_FETCH"  # replaced with the immutable asset URL at adoption
_PIN_ON_FIRST_FETCH_SHA = "0" * 64  # replaced with our SHA-256 of the pinned bytes at adoption
_UNPINNED_VERSION = "unpinned"  # replaced with the upstream export tag at adoption


def pp_doclayout_spec(models_dir: Path) -> ModelSpec:
    """Return the pinned PP-DocLayout (ONNX) :class:`ModelSpec` rooted under ``models_dir``."""

    return ModelSpec(
        id=PP_DOCLAYOUT_MODEL_ID,
        version=_UNPINNED_VERSION,
        license="Apache-2.0",
        target_dir=models_dir / PP_DOCLAYOUT_MODEL_ID,
        files=[
            ModelFile(
                name="doclayout.onnx",
                url=_PIN_ON_FIRST_FETCH_URL,
                sha256=_PIN_ON_FIRST_FETCH_SHA,
                size=0,
            ),
            ModelFile(
                name="label_map.txt",
                url=_PIN_ON_FIRST_FETCH_URL,
                sha256=_PIN_ON_FIRST_FETCH_SHA,
                size=0,
            ),
        ],
    )


def pp_ocrv5_det_spec(models_dir: Path) -> ModelSpec:
    """Return the pinned PP-OCRv5 text-detection (ONNX) :class:`ModelSpec`."""

    return ModelSpec(
        id=PP_OCRV5_DET_MODEL_ID,
        version=_UNPINNED_VERSION,
        license="Apache-2.0",
        target_dir=models_dir / PP_OCRV5_DET_MODEL_ID,
        files=[
            ModelFile(
                name="det.onnx",
                url=_PIN_ON_FIRST_FETCH_URL,
                sha256=_PIN_ON_FIRST_FETCH_SHA,
                size=0,
            ),
        ],
    )


def pp_ocrv5_rec_spec(models_dir: Path) -> ModelSpec:
    """Return the pinned PP-OCRv5 text-recognition (ONNX) :class:`ModelSpec`.

    ``rec_keys.txt`` is the character dictionary required to decode the rec head's class
    indices to characters — pinned as its own file (design §2.1).
    """

    return ModelSpec(
        id=PP_OCRV5_REC_MODEL_ID,
        version=_UNPINNED_VERSION,
        license="Apache-2.0",
        target_dir=models_dir / PP_OCRV5_REC_MODEL_ID,
        files=[
            ModelFile(
                name="rec.onnx",
                url=_PIN_ON_FIRST_FETCH_URL,
                sha256=_PIN_ON_FIRST_FETCH_SHA,
                size=0,
            ),
            ModelFile(
                name="rec_keys.txt",
                url=_PIN_ON_FIRST_FETCH_URL,
                sha256=_PIN_ON_FIRST_FETCH_SHA,
                size=0,
            ),
        ],
    )


def catalog(models_dir: Path) -> dict[str, ModelSpec]:
    """Return the full pinned catalog keyed by model id."""

    return {
        PIX2TEX_MODEL_ID: pix2tex_spec(models_dir),
        PP_DOCLAYOUT_MODEL_ID: pp_doclayout_spec(models_dir),
        PP_OCRV5_DET_MODEL_ID: pp_ocrv5_det_spec(models_dir),
        PP_OCRV5_REC_MODEL_ID: pp_ocrv5_rec_spec(models_dir),
    }
