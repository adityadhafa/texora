# M3 Design — PDF streaming + layout + text/formula pipeline + MD/LaTeX export

Status: Design v2 (revision — all m3-design-review findings F1–F7 resolved; see §17).
Worktree: `c:\data\kucing\texora\.worktrees\m3-pdf-pipeline`.
Scope: tasks **3.1–3.7** in `.kiro/specs/texora/tasks.md`. Requirements traced:
`R-ING-1/2/3/4`, `R-LAY-1/2/3`, `R-REC-1/2/6/7/8`, `R-EXP-1/2`, `R-LIC-1/2`, `R-SEC-3`, `R-QA-3`.

> **This is the project's headline feature.** The user's stated primary goal for the whole app is
> *high-accuracy PDF → Markdown (and LaTeX)* of math/scientific documents. M3 wires the first
> end-to-end document pipeline: a PDF (or image) goes in, a structured, reading-ordered,
> math-faithful Markdown/LaTeX document comes out — reusing the M2 pix2tex formula engine, never
> reinventing it. M3 is the *single-document, synchronous* pipeline; the job queue, checkpointing,
> and the 5,000-page streaming proof are **M4** and are explicitly out of scope here (the design is
> built so M4 slots on top without rework).

---

## 0. Overview

M3 adds four new engine packages and extends two existing ones, all under
`engine/texora_engine/`, and keeps the M2 seams intact:

- **`ingest/`** — `pypdfium2` page rendering (adaptive DPI with small-font raise), image loaders
  (Pillow + pillow-heif), and born-digital-vs-scanned detection. (3.1)
- **`ingest/preprocess.py`** — individually toggleable deskew / denoise / binarize / perspective /
  auto-crop. (3.2)
- **`layout/`** — a `layout/base.py` `LayoutDetector` Protocol + factory (mirror of
  `recognizers/`), a **permissive default** detector, and reading-order computation. (3.3, 3.4)
- **`recognizers/text_*.py`** — a `TextRecognizer` Protocol + PP-OCRv5 default and Tesseract
  fallback adapters (EN + ID first-class). (3.5)
- **`pipeline/` (new) — the page assembler** that merges regions by reading order into a typed
  `PageResult`, calling the text recognizer for text regions and the **M2 pix2tex
  `FormulaRecognizer`** for formula regions. (3.6)
- **`export/`** — Markdown (`$...$` / `$$...$$`) and LaTeX (`.tex` with preamble template)
  exporters, with golden-file fixtures. (3.7)

Every new engine (ingest renderer, layout detector, text recognizer) is a swappable adapter
selected by id from `pipeline.yaml`, exactly like the M2 formula recognizer. The HTTP API and the
Tauri UI depend only on the stable Protocols and the typed `PageResult`, never on a concrete
engine. All SQLite access (none is strictly required for the M3 synchronous path, but the new
model rows persist through the store) goes through `db/`/the model store. The engine stays
loopback-only with a bearer token on every non-health route.

**Honesty invariants carried from M2, enforced here too:** no fabricated OCR anywhere in a
production path. A region the layout/text/formula engine cannot recognize becomes
`needs_review`/`failed` in the `PageResult` — never a guess. No mocked OCR in the production code
path; recognition tests use real fixtures, export tests use golden files.

---

## 1. Technology stack (LOCKED on approval)

| Concern | Choice | Version (pin) | License | Verdict |
|---|---|---|---|---|
| PDF render | **pypdfium2** | 5.14.0 | BSD-3-Clause / Apache-2.0 | permissive — **shipped default** |
| Image decode | Pillow (M2) + **pillow-heif** | pillow 10.4.0 / pillow-heif 0.18.0 | Pillow HPND; pillow-heif BSD-3-Clause (libheif LGPL-3.0, dynamically linked) | permissive — default |
| Preprocess | **opencv-python-headless** (M2, already pinned) + numpy | 4.10.0.84 | Apache-2.0 | permissive — default |
| Layout detect (default) | **PP-DocLayout-L via PaddleX/PaddleOCR**, run through an **ONNX Runtime** inference path | paddleocr 3.7.x line (model exported to ONNX); onnxruntime 1.19.x | Apache-2.0 (code + PP-DocLayout weights) | permissive — **shipped default** |
| Layout detect (opt-in) | **DocLayout-YOLO** | doclayout-yolo 0.0.4 | **AGPL-3.0** | **opt-in only — NEVER default, not bundled** |
| Text OCR (default) | **PP-OCRv5 (PaddleOCR)** via ONNX Runtime | paddleocr 3.7.x / onnxruntime 1.19.x | Apache-2.0 | permissive — **shipped default** |
| Text OCR (fallback) | **Tesseract** via pytesseract | pytesseract 0.3.13 (+ system/bundled tesseract 5.x, Apache-2.0) | Apache-2.0 | permissive — fallback default |
| Formula OCR | **pix2tex (M2 adapter, reused as-is)** | pix2tex 0.1.4 | MIT | permissive — default (unchanged) |
| LaTeX validate/normalize | `pylatexenc` + KaTeX allow-list (M2 `ensemble/latex.py`, reused) | 2.10 | MIT | permissive |
| Markdown/LaTeX export | hand-written emitters (stdlib + Pydantic) | — | — | no new runtime dep |

See §7 for the full license verdict and the `docs/LICENSES.md` rows to add in this change
(`R-LIC-1`). The stack is locked once this design is approved; swapping an engine later is a
one-line `pipeline.yaml` change plus a new adapter file, never an API/UI change.

### 1.1 The ONNX Runtime decision for layout + text (and why not raw PaddlePaddle)

M2 deliberately avoided shipping the `paddlepaddle` runtime (the M2 design flag: PaddlePaddle's
Windows-CPU wheels + PyInstaller freezing are fragile, and PaddleX hub weights are hard to pin to
one stable URL+SHA-256). That reasoning still holds in M3. Therefore:

- We adopt the **PP-DocLayout** (layout) and **PP-OCRv5** (text det+rec) *models*, but run them
  through **ONNX Runtime** (`onnxruntime`, MIT), not the PaddlePaddle runtime. The weights are
  shipped as **`.onnx` files pinned in the model catalog** exactly like the pix2tex `.pth` files:
  immutable URL + pin-on-first-fetch SHA-256 + size, fetched only through Texora's own
  checksum-verified downloader (`R-INST-2/3`, `R-SEC-1`).
- This keeps the frozen-sidecar footprint and pinnability consistent with M2 and avoids a second
  heavyweight native runtime. `onnxruntime` CPU is the default execution provider; CUDA EP is the
  GPU path selected by the same `settings.device` the M2 hardware detector already exposes
  (`R-HW-1/2`).
- **Model provenance honesty:** the ONNX weights are exported from the official Apache-2.0
  PaddleOCR/PaddleX releases. We pin the exported artifact's URL + our-own SHA-256 (same
  pin-on-first-fetch honesty note as pix2tex in `docs/LICENSES.md`). If an official ONNX export is
  not published at a stable URL for a given model, the catalog pins a specific
  `rapid-layout` / `rapidocr-onnxruntime` (Apache-2.0) redistribution of the same PP model family,
  which republishes the PP-OCR/PP-Layout ONNX weights at versioned release assets — documented in
  the catalog note. Either way the license is Apache-2.0 and the bytes are pinned.

---

## 2. Module layout (new + changed files)

```
engine/texora_engine/
├─ ingest/                         # NEW (3.1, 3.2)
│  ├─ __init__.py                  # re-exports loaders + PageImage/RenderResult types
│  ├─ base.py                      # PageImage, RenderedPage, SourceKind, PdfTextLayer (typed models)
│  ├─ pdf.py                       # pypdfium2 renderer: adaptive DPI, small-font raise, text-layer extract
│  ├─ images.py                    # Pillow + pillow-heif loaders for PNG/JPG/TIFF/WEBP/BMP/HEIC
│  ├─ detect.py                    # born-digital vs scanned classification
│  └─ preprocess.py                # deskew/denoise/binarize/perspective/auto-crop (each toggleable)
├─ layout/                         # NEW (3.3, 3.4)
│  ├─ __init__.py
│  ├─ base.py                      # LayoutDetector Protocol + Region/RegionType/LayoutResult types
│  ├─ factory.py                   # id -> adapter registry; reads stages.layout from pipeline.yaml
│  ├─ pp_doclayout_onnx.py         # DEFAULT permissive detector (PP-DocLayout via onnxruntime)
│  ├─ born_digital.py              # structural detector from the pypdfium2 text layer (no model)
│  ├─ doclayout_yolo.py            # OPT-IN ONLY adapter (AGPL) — never registered as default
│  └─ reading_order.py             # XY-cut + column + equation-number ordering
├─ recognizers/                    # EXTENDED (3.5) — formula seam unchanged
│  ├─ base.py                      # ADD TextRecognizer Protocol + TextLine/TextResult types
│  ├─ text_factory.py              # id -> text adapter registry; reads stages.recognize.text
│  ├─ text_ppocr_onnx.py           # DEFAULT PP-OCRv5 text det+rec via onnxruntime (EN+ID)
│  └─ text_tesseract.py            # FALLBACK Tesseract adapter via pytesseract (EN+ID)
├─ pipeline/                       # NEW (3.6) — the page assembler
│  ├─ __init__.py
│  ├─ page_result.py               # typed PageResult / DocumentResult Pydantic models
│  └─ assembler.py                 # orchestrates ingest→layout→reading-order→recognize→PageResult
├─ export/                         # EXTENDED (3.7) — mathml.py unchanged
│  ├─ markdown.py                  # NEW: PageResult/DocumentResult -> Markdown ($...$ / $$...$$)
│  └─ latex.py                     # NEW: DocumentResult -> .tex with preamble template
├─ models/
│  └─ catalog.py                   # ADD pinned specs: pp_doclayout, pp_ocrv5_det, pp_ocrv5_rec
│                                  # (each ModelFile.name enumerated in §2.1 — a hard contract)
├─ pipeline_config.py              # EXTEND: Stages.ingest/layout concrete; RecognizeStage.text used
└─ api/
   └─ pages.py                     # NEW: POST /pages/recognize (single page/document, synchronous)
```

The streaming job runner, the `JOB/PAGE/REGION` SQLite tables, and `POST /jobs` are **M4** and are
not created here. `api/pages.py` is the synchronous single-document seam M4 will later drive from
its worker loop (the assembler is designed to be called per-page by M4 without change — see §9).

### 2.1 Stable adapter ids + model catalog contracts (resolves F1, F3, F6)

Every adapter declares a **stable `id`** string. The factory looks engines up by this exact
string from `pipeline.yaml`, so a mismatch is an `UnknownEngineError` at build time. These ids are
fixed by this design and MUST be used verbatim in the file, in `_REGISTRY`, and in `pipeline.yaml`:

| File | Declared `id` | Role | `model_ids` |
|---|---|---|---|
| `recognizers/text_ppocr_onnx.py` | `pp_ocrv5_onnx` | DEFAULT text | `("pp_ocrv5_det", "pp_ocrv5_rec")` |
| `recognizers/text_tesseract.py` | `tesseract` | FALLBACK text | `()` |
| `layout/pp_doclayout_onnx.py` | `pp_doclayout_onnx` | DEFAULT layout (model) | `("pp_doclayout",)` |
| `layout/doclayout_yolo.py` | `doclayout_yolo` | OPT-IN layout (AGPL) | `("doclayout_yolo",)` |
| `recognizers/formula_pix2tex.py` (M2) | `pix2tex` | DEFAULT formula | `("pix2tex",)` |

`layout/born_digital.py` is **not** a registry id — it is the assembler-owned structural fast-path
(§3.1), carries no `model_ids`, and is never written into `pipeline.yaml`.

The factory test (mirroring M2 `test_factory`) asserts for each built adapter that
`build_*(...).id == <configured id in pipeline.yaml>`, so an id drift is caught by a unit test, not
only at runtime.

**Model catalog rows and their `ModelFile.name`s (the `file_path(name)` contract).** `require_ready`
returns a `ModelSpec`; the adapter then calls `spec.file_path(name)`, which `KeyError`s on an
unpinned name (confirmed in `models/registry.py`). Every name an adapter will request is pinned
now; only URL+SHA-256 are pin-on-first-fetch at adoption (mirrors the pix2tex honesty note):

| Catalog `id` | `target_dir` | `ModelFile.name`s (pinned now) | License |
|---|---|---|---|
| `pp_doclayout` | `models_dir/pp_doclayout` | `doclayout.onnx`, `label_map.txt` | Apache-2.0 |
| `pp_ocrv5_det` | `models_dir/pp_ocrv5_det` | `det.onnx` | Apache-2.0 |
| `pp_ocrv5_rec` | `models_dir/pp_ocrv5_rec` | `rec.onnx`, `rec_keys.txt` (char dictionary) | Apache-2.0 |

The PP-OCR **recognizer character dictionary** (`rec_keys.txt`) is a required artifact for decoding
the rec head's class indices to characters; it is pinned as its own `ModelFile` on `pp_ocrv5_rec`
(the review correctly flagged its omission). `label_map.txt` maps PP-DocLayout class indices to the
`RegionType` taxonomy. These file names are the hard contract; the `.onnx`/dict bytes' URL+SHA are
pinned on first fetch, exactly like pix2tex.

**Multi-model resolution in the factories.** The M2 `build_formula_recognizer` resolves only
`entry.model_ids[0]`. The M3 text factory needs **two** catalog models plus a dictionary, so the
layout and text factories resolve **every** id in `model_ids` and pass explicit, named paths to the
adapter constructor:

```python
# recognizers/text_factory.py -- build_text_recognizer(settings, model_store)
entry = _REGISTRY[stage_id]                       # id == "pp_ocrv5_onnx"
specs = {mid: model_store.require_ready(mid) for mid in entry.model_ids}   # resolves ALL ids
return entry.ctor(
    det_onnx=specs["pp_ocrv5_det"].file_path("det.onnx"),
    rec_onnx=specs["pp_ocrv5_rec"].file_path("rec.onnx"),
    dict_path=specs["pp_ocrv5_rec"].file_path("rec_keys.txt"),
    langs=("en", "id"),
    device=settings.device,
)

# layout/factory.py -- build_layout_detector(settings, model_store)
entry = _REGISTRY[stage_id]                        # id == "pp_doclayout_onnx"
specs = {mid: model_store.require_ready(mid) for mid in entry.model_ids}
return entry.ctor(
    layout_onnx=specs["pp_doclayout"].file_path("doclayout.onnx"),
    label_map=specs["pp_doclayout"].file_path("label_map.txt"),
    device=settings.device,
)
```

The dict-comprehension over `entry.model_ids` means **each** id is verified by `require_ready`
(every missing model raises `ModelNotReady`, not just the first). Adapter constructor signatures:

- `Pix2TexFormulaRecognizer(checkpoint_path, resizer_path, device)` — M2, unchanged.
- `PpOcrV5TextRecognizer(det_onnx: Path, rec_onnx: Path, dict_path: Path, langs: tuple[str, ...], device: str)`.
- `TesseractTextRecognizer(langs: tuple[str, ...], tesseract_cmd: str | None, data_dir: str | None)` —
  no `model_ids`, so the factory builds it with no `require_ready` call (see §7.2 for the
  fallback-build path).
- `PpDocLayoutOnnxDetector(layout_onnx: Path, label_map: Path, device: str)`.

---

## 3. CRITICAL license decision — the default layout engine (resolved here)

Task 3.3 names **DocLayout-YOLO** as the layout model and instructs: *verify its license; if AGPL
or otherwise non-permissive, it must be opt-in only and NOT the shipped default.* Verified against
official sources on 2026-10-18 (recorded with the `docs/LICENSES.md` rows added in this change):

- **`doclayout-yolo` 0.0.4 (PyPI)** → classifier `License :: OSI Approved :: GNU Affero General
  Public License v3 or later (AGPLv3+)`, `license: AGPL-3.0`.
- **`opendatalab/DocLayout-YOLO` (GitHub)** → repository license `AGPL-3.0`.
- **`ultralytics` 8.4.x (the lineage)** → `AGPL-3.0`.

**Verdict: DocLayout-YOLO is AGPL-3.0 (code and the Ultralytics-lineage runtime). It is OPT-IN
ONLY, is NEVER the shipped default, and is NOT bundled in the redistributable installer**
(`R-LIC-2`). Its adapter (`layout/doclayout_yolo.py`) exists so a user can *locally* choose it, but
it is **not registered in the default factory registry** and requires the same explicit
acknowledgment gate the M2 design reserves for Surya/PyMuPDF. Its `docs/LICENSES.md` row goes in
the "Deferred / opt-in only" section, next to PyMuPDF and Surya.

### 3.1 The chosen PERMISSIVE default layout approach

The shipped default is a **two-path permissive layout stage**, chosen over a single model because
the headline input is a *mix* of born-digital and scanned math PDFs and the permissive-first rule
forbids the AGPL model:

1. **Born-digital path (`layout/born_digital.py`, no model, no download).** When
   `ingest/detect.py` classifies a PDF page as born-digital (reliable embedded text), regions are
   derived structurally from the **pypdfium2 text layer**: text blocks/lines with their bounding
   boxes come directly from pdfium, column structure from x-interval clustering, and *math regions*
   from a heuristic pass (glyph-run gaps, math-font / Unicode-math detection, isolated
   display-equation lines, trailing `(n)` equation numbers). This path is permissive by
   construction (pypdfium2 is BSD/Apache) and is the fastest, most accurate route for the common
   born-digital case — no model inference at all.

2. **Model path (`layout/pp_doclayout_onnx.py`, DEFAULT model).** When a page is scanned (or the
   born-digital structural signal is weak), region detection runs **PP-DocLayout** (from the
   Apache-2.0 PaddleOCR/PaddleX family) through **ONNX Runtime**. This yields the full region-type
   taxonomy (`R-LAY-1`) with bboxes and per-region confidence (`R-LAY-3`). **Apache-2.0 for both
   code and weights → permissive, shipped default.**

**Named permissive default:** `pipeline.yaml` sets `stages.layout: pp_doclayout_onnx`, and the
assembler routes born-digital pages through `born_digital` automatically (the born-digital detector
is not a separately-selected engine id — it is an always-available structural fast-path owned by
the assembler; the configured `stages.layout` engine is what runs when a model is needed). This
keeps the *shipped default* fully Apache-2.0/BSD and model-downloadable through the pinned catalog,
with zero AGPL/non-commercial code in the default path.

**Fallback if PP-DocLayout ONNX cannot be pinned to a stable URL at adoption:** the catalog instead
pins the Apache-2.0 **`rapid-layout`** redistribution of the same PP-Layout ONNX weights (same
license verdict, versioned release assets). The adapter id and Protocol are unchanged; only the
catalog URL/SHA changes. This is recorded as the documented contingency, not a silent fallback.

### 3.2 Other license confirmations required by the task

- **PDF render default — pypdfium2** = BSD-3-Clause / Apache-2.0 → **permissive, shipped default.**
  **PyMuPDF (fitz)** = AGPL-3.0 → opt-in only, never default (already in the `docs/LICENSES.md`
  deferred section; M3 adds no PyMuPDF dependency).
- **Text OCR default — PP-OCRv5 (PaddleOCR)** = Apache-2.0 (code + weights) → **permissive,
  shipped default.** **Tesseract / pytesseract** = Apache-2.0 → permissive fallback.
- **onnxruntime** = MIT; **pillow-heif** = BSD-3-Clause (bundled libheif is LGPL-3.0, dynamically
  linked, redistributable) → permissive.

No AGPL or non-commercial component is in the M3 default path.

---

## 4. Ingestion — task 3.1 (`R-ING-1/2/3`)

### 4.1 Typed models (`ingest/base.py`)

```python
class SourceKind(StrEnum):
    PDF_BORN_DIGITAL = "pdf_born_digital"
    PDF_SCANNED = "pdf_scanned"
    IMAGE = "image"

class PdfTextSpan(BaseModel):     # one positioned text run from the pdfium text layer
    text: str
    bbox: tuple[float, float, float, float]   # x0,y0,x1,y1 in RENDERED-image pixels
    font_size_pt: float
    is_mathish: bool = False      # set by the math heuristic (born-digital path)

class RenderedPage(BaseModel):
    index: int                    # 0-based page index
    width: int                    # rendered pixel width
    height: int
    dpi: int                      # effective DPI used (post small-font raise)
    kind: SourceKind
    text_layer: list[PdfTextSpan] | None  # present iff born-digital PDF; None for scanned/image
    # The PIL.Image is NOT stored on the model (kept out of the serialized result and freed
    # promptly, R-SEC-3). It is passed alongside the RenderedPage within the assembler only.
```

`RenderedPage` is JSON-serializable (no bitmap). The bitmap travels as a separate
`PIL.Image.Image` handle inside the assembler and is explicitly closed after the page's regions are
recognized (`image.close()` + drop references), keeping memory ≈ constant for M4's streaming.

### 4.2 PDF rendering (`ingest/pdf.py`)

- Open with `pypdfium2.PdfDocument(path)`. Iterate pages lazily (`for i in range(len(pdf))`) — the
  whole document is never materialized; one page bitmap exists at a time (M4-ready).
- **Adaptive DPI (`R-ING-2`):** render at `settings.ingest.base_dpi` (default **260**, within the
  220–300 band). After an initial render, estimate the **median glyph height** from the text layer
  (born-digital) or from a fast connected-component size estimate (scanned). If the median glyph
  cap-height is below `settings.ingest.small_font_px` (default 12 px), **re-render once** at
  `min(base_dpi * raise_factor, max_dpi)` (`raise_factor` default 1.5, `max_dpi` default 400). One
  re-render max per page — bounded work, no loops.
- Use `page.render(scale=dpi/72.0).to_pil()` to get a `PIL.Image`. Convert to RGB.
- **Text-layer extraction (born-digital):** `page.get_textpage()` → iterate rects/chars to build
  `PdfTextSpan`s, converting pdfium's point coordinates (origin bottom-left, 72 dpi) to
  rendered-image pixel coordinates (origin top-left, at the effective DPI). This conversion is the
  one fiddly invariant; it is unit-tested against a known fixture (§8).

### 4.3 Image loaders (`ingest/images.py`)

- PNG/JPG/JPEG/WEBP/BMP via Pillow (already pinned). Multi-page **TIFF** via Pillow's
  `ImageSequence` (each frame → one `RenderedPage` with `kind=IMAGE`). **HEIC/HEIF** via
  `pillow-heif` (`register_heif_opener()` once at import). Clipboard/screen-region images reuse the
  M2 decode path (bytes → `Image.open`).
- Reuse the **M2 decompression-bomb guards** (`Image.MAX_IMAGE_PIXELS`, plus explicit
  area/edge/byte bounds from settings) on every loaded image (`R-SEC-3`). A file that fails to
  decode or exceeds bounds raises a typed error the API maps to 422 (per-image), never crashing a
  multi-page/document run.

### 4.4 Born-digital vs scanned detection (`ingest/detect.py`) — `R-ING-3`

Classify per page (a PDF can mix): a page is **born-digital** iff pdfium reports extractable text
covering ≥ `settings.ingest.born_digital_char_threshold` characters **and** the text's bounding
boxes cover ≥ `settings.ingest.born_digital_coverage` (default 0.05) of the page area; otherwise
**scanned**. Returns a `SourceKind` per page. Pure function over the pdfium text page; unit-tested
on a born-digital fixture (positive) and a rasterized/scanned fixture (negative).

**`R-ING-3` nuance honored:** even on a born-digital page where plain text is taken from the text
layer, **formula regions still run the pix2tex recognizer** — the text layer's math is unreliable
(ligatures, missing scripts), so math regions are always re-recognized from the rendered crop. The
assembler enforces this (§7.4).

---

## 5. Preprocessing — task 3.2 (`R-ING-4`)

`ingest/preprocess.py` exposes one pure function per step, each **individually toggleable** via
`pipeline.yaml` → Pydantic settings (no magic constants, `R-ING-4`):

```python
class PreprocessSettings(BaseModel):      # under settings; mirrored in pipeline.yaml ingest block
    deskew: bool = True
    denoise: bool = True
    binarize: bool = False     # default off: color/grayscale preserved for the recognizers
    perspective: bool = False  # default off: only helps photographed pages
    auto_crop: bool = True

def preprocess(img: Image.Image, cfg: PreprocessSettings, kind: SourceKind) -> Image.Image: ...
```

- **deskew** — estimate skew via OpenCV minAreaRect over foreground mask / Hough; rotate within
  ±15°; skip if |angle| < 0.3°.
- **denoise** — `cv2.fastNlMeansDenoising` (grayscale) / median blur for scanned pages only.
- **binarize** — adaptive threshold (Sauvola/Otsu); **off by default** (PP-OCRv5 and pix2tex prefer
  grayscale/color input; binarization can hurt). Opt-in for degraded scans.
- **perspective** — four-point transform from the largest quadrilateral contour; off by default.
- **auto_crop** — trim surrounding whitespace/margins via foreground bounding box with a small pad.

Each step is skipped entirely when its flag is false (`R-ING-4` "disable each step"). Born-digital
pages default to **no preprocessing** (the rendered page is already clean) unless flags are forced
on. Steps are applied in the fixed order deskew → perspective → denoise → binarize → auto_crop;
each returns a new image and the caller frees the previous. Tested with **before/after fixtures**
asserting toggles are respected (a disabled step is a no-op; an enabled step changes pixels in the
expected direction — e.g. deskew reduces measured skew angle).

---

## 6. Layout + reading order — tasks 3.3 & 3.4 (`R-LAY-1/2/3`)

### 6.1 `layout/base.py` Protocol shape (mirror of `recognizers/base.py`)

```python
class RegionType(StrEnum):
    TITLE = "title"; PARAGRAPH = "paragraph"; INLINE_MATH = "inline_math"
    DISPLAY_MATH = "display_math"; EQUATION_NUMBER = "equation_number"
    TABLE = "table"; FIGURE = "figure"; CAPTION = "caption"; FOOTNOTE = "footnote"
    HEADER = "header"; FOOTER = "footer"; LIST = "list"; CODE = "code"
    HANDWRITING = "handwriting"; UNKNOWN = "unknown"      # full R-LAY-1 taxonomy

class BBox(BaseModel):
    x0: float; y0: float; x1: float; y1: float   # rendered-image pixels, top-left origin

class Region(BaseModel):
    type: RegionType
    bbox: BBox
    confidence: float = Field(ge=0.0, le=1.0)    # R-LAY-3
    reading_order: int = -1                       # filled by reading_order.py (-1 = unset)
    source: str = "model"                         # "model" | "born_digital"

class LayoutResult(BaseModel):
    regions: list[Region]
    engine_id: str

@runtime_checkable
class LayoutDetector(Protocol):
    id: str
    model_ids: tuple[str, ...]
    def detect(self, image: Image.Image, page: RenderedPage) -> LayoutResult:
        """Pure detection. MUST catch its own inference errors and return an empty
        LayoutResult (regions=[]) with engine_id set, NEVER raise — a failed detection
        downgrades the whole page to needs_review in the assembler, never fabricates regions."""
        ...
```

Same contract style as the formula recognizer: stable `id`, `model_ids` declared by the adapter,
pure `detect(...)`, typed Pydantic result, errors caught internally. `page` is passed so the
born-digital detector can read the text layer.

### 6.2 `layout/factory.py`

Identical structure to `recognizers/factory.py`: a `_REGISTRY: dict[str, _Entry]` of **permissive**
adapters only, `build_layout_detector(settings, model_store)` reads
`load_pipeline_config().stages.layout`, raises `LayoutStageNotConfigured` /
`UnknownLayoutEngineError` (never a silent default), and resolves weights via the adapter's
`model_ids` through `model_store.require_ready(...)`. **`doclayout_yolo` is intentionally absent
from `_REGISTRY`** (opt-in only; a user enabling it goes through the same explicit-acknowledgment
registration the M2 design reserves for opt-in engines, not the default factory).

### 6.3 Default detectors

- **`pp_doclayout_onnx.py`** — loads the pinned PP-DocLayout `.onnx` via `onnxruntime.InferenceSession`
  (CPU EP default; CUDA EP when `settings.device == "cuda"`). Preprocess → infer → decode boxes to
  `Region`s with the PP label map collapsed into `RegionType`. Confidence = model score. `model_ids
  = ("pp_doclayout",)`. On any inference exception: log + return `LayoutResult(regions=[],
  engine_id=self.id)` (never raise, never fabricate).
- **`born_digital.py`** — no model, no `model_ids`. Builds `Region`s from `page.text_layer`: cluster
  spans into lines → blocks; classify each block as `PARAGRAPH` / `TITLE` (font-size percentile) /
  `INLINE_MATH` or `DISPLAY_MATH` (math-heuristic density + isolation) / `EQUATION_NUMBER`
  (right-margin `(n)` pattern) / `LIST` (leading bullet/number) / `CAPTION`/`FOOTNOTE`
  (position+size). Confidence is a structural heuristic score (documented as heuristic, not a model
  probability — honest `confidence_kind` analog in the detail).

### 6.4 Reading order (`layout/reading_order.py`) — `R-LAY-2`

Pure function `order(regions: list[Region], width: int, height: int) -> list[Region]` (sets
`reading_order`). It takes the page **`width` and `height` only** — used for the column-gutter and
XY-cut whitespace thresholds — not the whole `RenderedPage`; bboxes and types are already on each
`Region`. This keeps the contract a minimal pure function (resolves F7):

- **Column detection** — project region x-centers onto the x-axis; find vertical gutters (empty
  x-bands wider than a `width`-relative threshold) to split into N columns. Single-column when no
  gutter.
- **Recursive XY-cut** — standard XY-cut: alternately cut the page by the widest horizontal/vertical
  whitespace gap, recursing, to produce a globally consistent top-to-bottom, left-to-right order
  that handles multi-column correctly.
- **Equation-number handling** — a right-margin `EQUATION_NUMBER` region is *attached to* the
  nearest `DISPLAY_MATH` region on the same horizontal band and ordered immediately after it (not
  as a separate stray line), so the numbering stays with its equation in the output. Headers/footers
  are ordered out-of-band (emitted first/last or dropped per export settings).
- **Intra-line run order (inline math, resolves F5)** — reading order operates at two levels. The
  *block* level orders regions as above. *Within* a text block that contains inline math, the
  born-digital detector (or, on the model path, the inline-math sub-detector in §6.6) emits the
  block's `InlineRun`s already left-to-right/top-to-bottom by each run's x/y within the line; the
  block's `reading_order` is the block integer, and the run list order is the intra-block sequence.
  The exporter concatenates runs in list order, so inline `$...$` lands at its true position in the
  paragraph's flow — not before/after the block.

Tested on a **two-column fixture** (correct interleaved order), a **display-equation +
right-number fixture** (number binds to its equation), and a **paragraph-with-inline-math fixture**
(runs ordered text→math→text within the line). Pure and deterministic → fully unit-testable.

### 6.5 Inline-math runs inside a text block (resolves F5) — how `inlines` is built

The headline goal requires inline math to render **inside** a paragraph's text, e.g.
`the energy $E = mc^2$ is conserved`. The `INLINE_MATH` region type remains in the taxonomy (a
page may have a standalone inline-math fragment), but the primary mechanism is **inline runs
carried on the containing text block**, because a flat list of sibling regions cannot express
"math at character offset k within this paragraph":

- **Born-digital path (default for born-digital PDFs).** `born_digital.py` already has per-span
  positions and the `is_mathish` flag from the math heuristic (§4.2, §6.3). It splits each text
  block's line into consecutive runs: contiguous non-math spans become a `TEXT` run; each maximal
  run of `is_mathish` spans becomes a `MATH` run whose rendered crop (union bbox of its spans) is
  sent to the pix2tex `FormulaRecognizer`. The block's `RegionContent.inlines` is the ordered run
  list. A paragraph with no math is a single `TEXT` run.
- **Model path (scanned pages).** PP-DocLayout emits block regions plus any `INLINE_MATH` sub-boxes
  it detects. The assembler assigns each detected `INLINE_MATH` box to the enclosing text block by
  bbox containment, runs text OCR on the non-math remainder and pix2tex on the math box, and
  interleaves them into `inlines` ordered by x (same-line) then y. If no inline-math box is detected
  inside a block, the block is a single `TEXT` run (OCR output). This is lower-fidelity than the
  born-digital path (OCR has no per-glyph math flag), which is honest and acceptable: scanned inline
  math that the layout model misses stays in the OCR text run, never fabricated.

Either way the exporter (§8) sees a uniform `inlines: list[InlineRun]` and does not need to know
which path produced it. A `MATH` run that pix2tex fails on becomes a run with
`status=needs_review` and a `detail`, surfaced by the review marker — never guessed.

### 6.6 Edge cases

- Overlapping regions → keep the higher-confidence/more-specific type; nest `CAPTION` under
  `FIGURE`/`TABLE` by containment.
- Empty page (blank/scanned-blank) → `LayoutResult(regions=[])` → assembler emits an empty page,
  not a failure.
- Rotated page → deskew (preprocess) runs before layout; layout always sees an upright image.

---

## 7. Recognition + page assembly — tasks 3.5 & 3.6 (`R-REC-1/8`, `R-EXP-1`)

### 7.1 Text recognizer Protocol (added to `recognizers/base.py`)

```python
class TextLine(BaseModel):
    text: str
    bbox: BBox
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_kind: ConfidenceKind = ConfidenceKind.TOKEN_LOGPROB  # or UNAVAILABLE

class TextResult(BaseModel):
    lines: list[TextLine]
    status: RecognitionStatus = RecognitionStatus.OK
    engine_id: str
    detail: str | None = None

@runtime_checkable
class TextRecognizer(Protocol):
    id: str
    model_ids: tuple[str, ...]
    langs: tuple[str, ...]                      # e.g. ("en","id")
    def recognize(self, image: Image.Image, ctx: RegionContext) -> TextResult:
        """Recognize text in a cropped region. Pure; catches own errors → status=FAILED,
        never raises, never fabricates (R-REC-8)."""
        ...
```

This reuses the M2 `RecognitionStatus`, `ConfidenceKind`, `RegionContext`, and `BBox` — one source
of truth across formula + text so the `'ok' | 'needs_review' | 'failed'` literals cross the
TS boundary unchanged.

### 7.2 Text adapters (`R-REC-1`, EN + ID first-class)

- **`text_ppocr_onnx.py` (DEFAULT)** — PP-OCRv5 detection + recognition via `onnxruntime`.
  `model_ids = ("pp_ocrv5_det", "pp_ocrv5_rec")`, `langs = ("en","id")` (PP-OCRv5's Latin
  recognizer covers both; ID uses the Latin script model). Real per-line confidence from the rec
  head → `TOKEN_LOGPROB`. On inference error → `status=FAILED`, empty lines, never a guess.
- **`text_tesseract.py` (FALLBACK)** — `id = "tesseract"`. `pytesseract.image_to_data` with
  `lang="eng+ind"`, confidence from Tesseract's per-word conf (normalized 0–1). `model_ids = ()`
  (Tesseract uses its own traineddata, Apache-2.0, located via `settings` / PATH — not the model
  store). Selected explicitly by `stages.recognize.text: tesseract`, **or** substituted
  automatically when the PP-OCRv5 model is absent and fallback is enabled (see §7.2.1).

A `recognizers/text_factory.py` mirrors the formula/layout factories, reading
`stages.recognize.text`.

### 7.2.1 Tesseract-fallback trigger — one owning layer (resolves F2)

In the live code, `model_store.require_ready` raises `ModelNotReady` at **factory build time**
(inside `build_*_recognizer`), never inside `recognize`. So the fallback decision is owned by
**`build_text_recognizer`**, not the assembler, and there is exactly one place the condition is
evaluated. This also removes the apparent conflict between "auto-fallback" (§7.2) and the 409 in
§12 — they are the two branches of a single decision:

```python
# recognizers/text_factory.py
def build_text_recognizer(settings: Settings, model_store: ModelStore) -> TextRecognizer:
    stage_id = load_pipeline_config().stages.recognize.text
    if stage_id is None:
        raise TextStageNotConfigured()
    if stage_id not in _REGISTRY:
        raise UnknownTextEngineError(stage_id, known=known_text_engine_ids())
    entry = _REGISTRY[stage_id]

    # Explicitly-selected Tesseract: no model store resolution (model_ids == ()).
    if stage_id == "tesseract":
        return _build_tesseract(settings)       # raises TesseractUnavailable -> 409 if not usable

    try:
        specs = {mid: model_store.require_ready(mid) for mid in entry.model_ids}
    except ModelNotReady:
        if settings.recognize.text_fallback_to_tesseract and _tesseract_available(settings):
            logger.info("text degrade: PP-OCRv5 weights absent -> falling back to tesseract")
            return _build_tesseract(settings)    # honest, logged degrade
        raise                                    # -> api/pages.py maps to 409 (prompt download)

    return entry.ctor(det_onnx=..., rec_onnx=..., dict_path=..., langs=("en","id"),
                      device=settings.device)
```

Decision table (the 409-vs-fallback branch is now deterministic):

| PP-OCRv5 weights | `text_fallback_to_tesseract` | Tesseract usable | Result |
|---|---|---|---|
| present | — | — | PP-OCRv5 adapter |
| absent | true | yes | Tesseract adapter (INFO-logged degrade; `engine_id="tesseract"` on every line) |
| absent | true | no | **409** `model_not_ready` (nothing usable; prompt download) |
| absent | false | — | **409** `model_not_ready` |

**"Tesseract usable"** = `_tesseract_available(settings)`: the `tesseract` binary resolves
(`settings.recognize.tesseract_cmd` if set, else on `PATH`) **and** a probe
(`pytesseract.get_tesseract_version()`) succeeds. If a user explicitly sets `text: tesseract` but
the binary is missing, `_build_tesseract` raises `TesseractUnavailable`, which `api/pages.py` maps
to **409** with a clear "install/point to Tesseract" message — never a silent no-op, never a mock.

Honesty is preserved end-to-end: the chosen engine stamps `engine_id` on every `TextLine` and on
each `RegionContent`, so a degrade from PP-OCRv5 to Tesseract is visible in the `DocumentResult` and
in the UI, not hidden.

### 7.3 Typed page-result model (`pipeline/page_result.py`) — `R-EXP-1`

```python
class RunKind(StrEnum):
    TEXT = "text"
    MATH = "math"                           # inline math ($...$), recognized by pix2tex

class InlineRun(BaseModel):
    """One ordered span inside a paragraph/title line. The exporter concatenates runs
    in list order to reproduce true in-paragraph inline math (resolves F5)."""
    kind: RunKind
    text: str | None = None                 # populated iff kind == TEXT
    latex: str | None = None                # populated iff kind == MATH (validated/normalized)
    mathml: str | None = None               # populated iff kind == MATH
    status: RecognitionStatus = RecognitionStatus.OK
    confidence: float = 0.0
    confidence_kind: ConfidenceKind = ConfidenceKind.UNAVAILABLE
    engine_id: str = ""
    detail: str | None = None

class RegionContent(BaseModel):
    region: Region                          # type, bbox, reading_order, confidence
    # A text-ish region carries an ORDERED list of inline runs (text + inline-math runs),
    # so inline math is placed at its true position within the paragraph's flow. A plain
    # paragraph is simply a single TEXT run. Block math/other regions use latex/text below.
    inlines: list[InlineRun] = Field(default_factory=list)   # for text-ish regions
    text: str | None = None                 # convenience flattening of inlines' text (plain regions)
    latex: str | None = None                # for BLOCK math regions (DISPLAY_MATH), validated
    mathml: str | None = None               # for BLOCK math regions
    status: RecognitionStatus = RecognitionStatus.OK
    confidence: float = 0.0
    confidence_kind: ConfidenceKind = ConfidenceKind.UNAVAILABLE
    engine_id: str = ""                      # which recognizer produced this
    detail: str | None = None

class PageResult(BaseModel):
    index: int
    width: int; height: int; dpi: int
    kind: SourceKind
    contents: list[RegionContent]            # in reading order
    status: RecognitionStatus                # worst-of the regions (ok/needs_review/failed)

class DocumentResult(BaseModel):
    source_name: str
    pages: list[PageResult]                  # M3: synchronous, all pages in memory for one doc;
                                             # M4 streams these to SQLite/disk per page instead.
```

This is the stable contract the exporters and the UI consume. It carries bboxes + confidence +
reading order (satisfies the JSON-export requirement `R-EXP-2` for free) and preserves structure,
reading order, and equation numbering (`R-EXP-1`).

### 7.4 Assembler (`pipeline/assembler.py`) — the orchestration, `R-EXP-1`, `R-REC-8`

`assemble_page(rendered: RenderedPage, image: Image.Image, deps: PipelineDeps) -> PageResult`:

1. **Preprocess** the image per settings (skipped for clean born-digital pages).
2. **Layout**: if `rendered.kind == PDF_BORN_DIGITAL`, use the born-digital structural detector;
   else call the configured `LayoutDetector` (`pp_doclayout_onnx`). → `LayoutResult`.
3. **Reading order**: `reading_order.order(regions, rendered.width, rendered.height)` → ordered
   regions (block-level `reading_order` ints; intra-block run order per §6.5).
4. **Per-region recognition** (bounded, timed — see §7.5):
   - `PARAGRAPH/TITLE/CAPTION/FOOTNOTE/LIST/CODE/HEADER/FOOTER` (text-ish) → build
     `RegionContent.inlines` as an ordered run list (§6.5): each `TEXT` run comes from the text
     recognizer (or, for born-digital, the **text-layer text directly** — faster and lossless), and
     each inline-`MATH` run from the pix2tex `FormulaRecognizer` on the math sub-crop. A paragraph
     with no inline math is a single `TEXT` run. `RegionContent.text` is the flattened plain text of
     the `TEXT` runs (convenience for plain regions); the inline-math placement lives in `inlines`.
   - `INLINE_MATH` as a standalone region (no enclosing text block) and `DISPLAY_MATH` → crop →
     **M2 `FormulaRecognizer` (pix2tex), reused via `build_formula_recognizer`** →
     `validate_and_normalize` (M2 `ensemble/latex.py`) → `latex_to_mathml` (M2 `export/mathml.py`)
     → `RegionContent.latex/mathml`. **Always re-recognized from the crop even on born-digital
     pages** (`R-ING-3`). A standalone `INLINE_MATH` region is also representable as a single-`MATH`
     run so the exporter can inline it when it belongs to a line; a truly isolated one is emitted as
     its own inline `$...$` fragment.
   - `EQUATION_NUMBER` → attached to its display-math region (plain text extraction).
   - `TABLE` → **M3 scope-limited:** detected and its bbox/crop preserved in the `PageResult` with
     `type=TABLE` and `status=needs_review` + detail `"table recognition is M6"` — **never
     fabricated**. Full SLANet table recognition is task **6.1 (M6)**.
   - `FIGURE` → crop saved to the output asset dir; `RegionContent.text=None`, referenced in export
     (`R-EXP-1` "figures cropped and saved").
   - `HANDWRITING` → `status=needs_review`, detail `"handwriting path is M6"` (task 6.5). Never
     guessed.
5. **Status roll-up**: `PageResult.status` = worst of its regions
   (`failed > needs_review > ok`).
6. **Free the bitmap** (`image.close()`) and any crops before returning (`R-SEC-3`, M4-ready
   constant memory).

`PipelineDeps` bundles the built layout detector, text recognizer, and formula recognizer (all
constructed once and cached on `app.state`, like the M2 formula singleton) plus settings — so the
assembler is a pure function of its inputs and fully unit-testable with real fixtures.

**No fabrication guarantee (`R-REC-8`):** every unrecognized/failed/unsupported region becomes
`needs_review`/`failed` with a `detail`, never an invented value. There is no mocked OCR in this
path.

### 7.5 Per-region resource safety (`R-SEC-3`)

Each region recognition runs under a **per-region timeout** (`settings.page.region_timeout_s`,
default 30 s) via the same single-worker `ThreadPoolExecutor` + `asyncio.wait_for` pattern the M2
snip route uses (torch/onnxruntime sessions are serialized). A timeout or exception marks **that
region** `failed` and the page continues — a hostile region never kills the page or document
(mirrors the M2 isolation; M4 extends this to per-page job isolation). Crops are freed immediately
after each region.

### 7.6 API seam (`api/pages.py`)

`POST /pages/recognize` (bearer-protected, `protected_router` pattern): accepts a file path
(validated/sanitized, `R-SEC-3`) or an uploaded image + options (DPI override, preprocess toggles,
page range). Runs the assembler synchronously over the document and returns `DocumentResult`.
Model-not-ready → 409 (prompt download); misconfiguration → 500 with a clear message; bad
input/path → 422 — identical error-mapping discipline to the M2 `recognize.py`. This endpoint is
the synchronous M3 deliverable; M4 adds the async `POST /jobs` streaming variant over the same
assembler.

---

## 8. Markdown + LaTeX export — task 3.7 (`R-EXP-2`), THE HEADLINE OUTPUT

### 8.1 Markdown exporter (`export/markdown.py`)

`document_to_markdown(doc: DocumentResult, opts: MarkdownOptions) -> str`. Walks pages → regions in
reading order and emits clean Markdown:

- `TITLE` → `#`/`##` by level (first title on page = `#`); emitted by concatenating its `inlines`.
- `PARAGRAPH` → one text paragraph produced by concatenating `RegionContent.inlines` in order:
  each `TEXT` run is emitted verbatim and each `MATH` run is wrapped `$<latex>$`, so inline math
  lands at its true position inside the paragraph (resolves F5 — the exporter never has to guess
  before/after placement; the ordered run list carries it). A `MATH` run with
  `status != ok` is emitted as `$<latex-or-empty>$` followed by its `<!-- needs_review -->` marker,
  honest about the uncertain span.
- `DISPLAY_MATH` → `$$\n<latex>\n$$`, with an attached equation number rendered as
  `$$<latex> \tag{n}$$` (KaTeX/Pandoc-compatible `\tag`).
- `LIST` → `-`/`1.` items. `CODE` → fenced block. `TABLE` → the detected-but-unrecognized table
  emitted as an HTML comment placeholder `<!-- table: needs_review (M6) -->` plus the cropped image
  reference — **honest**, never a fabricated table. `FIGURE` → `![caption](assets/fig_p<page>_<n>.png)`.
- Regions with `status != ok` get an inline marker comment `<!-- needs_review: <detail> -->` so the
  UI/review flow can surface them and the Markdown stays truthful. No region is silently dropped
  and none is fabricated.

`MarkdownOptions` (from settings/pipeline.yaml): `math_delimiters` (`dollar` default), `emit_tags`
(equation numbers), `include_review_markers`, `figure_asset_dir`.

### 8.2 LaTeX exporter (`export/latex.py`)

`document_to_latex(doc, opts) -> str`. Emits a compilable `.tex` with a **preamble template**:

- Preamble template selected by `opts.preamble` (`article` default) → `\documentclass{article}` +
  `amsmath, amssymb, graphicx, booktabs` + UTF-8 input. Templates live as config (Pydantic/settings
  + a `templates/` string), not magic constants.
- Body: `TITLE`→`\section`; paragraphs emitted by concatenating `inlines` (each `TEXT` run verbatim,
  each `MATH` run wrapped `$...$`) so inline math sits at its true in-paragraph position (resolves
  F5, same run model as the Markdown exporter); display math in
  `\begin{equation}...\end{equation}` (numbered when an equation number is attached, else
  `equation*`); figures `\includegraphics`; tables → placeholder comment + crop include (M6 fills
  real tabular). `needs_review` regions emit a `% needs_review: ...` comment.
- The emitted LaTeX only uses macros within the KaTeX/amsmath-supported set already validated by
  `ensemble/latex.py`, so the golden `.tex` **compiles with the documented preamble** (`R-EXP-4`
  foundation; M6 extends exports).

### 8.3 Testing the exporters (golden files, `R-QA-3`)

Exports are tested with **golden-file fixtures** under `engine/tests/golden/`: a fixed
`DocumentResult` (constructed in-test from known regions — this is test data, not mocked OCR of a
production path) renders to a byte-stable `.md` and `.tex`.

**The LaTeX-compile check is NON-SKIPPABLE in CI (resolves F4).** `tasks.md` 3.7 `done:` is "golden
export; **LaTeX compiles**" — the headline deliverable. A silent xfail-skip when TeX is absent would
make that done-check vacuous. Therefore:

- A dedicated engine CI job (`m3-latex-compile`) **provisions a minimal TeX toolchain** —
  `latexmk` + `texlive-latex-recommended` + `texlive-latex-extra` on Linux CI (or TinyTeX with the
  `amsmath, amssymb, graphicx, booktabs` packages) — and runs
  `latexmk -pdf -interaction=nonstopmode` on the golden `.tex`, asserting **exit 0**. This job is
  gated like the `@pytest.mark.model` weights job: it provisions its dependency rather than
  skipping, so a non-compiling `.tex` **fails CI**.
- The test is marked `@pytest.mark.latex`. **Local dev** may xfail-skip when no TeX toolchain is
  found (developer convenience), but **CI must run it** (the CI job installs the toolchain and runs
  `pytest -m latex` with `--runxfail`/no-skip so an absent toolchain is a CI configuration error,
  not a silent pass). The design records this as a hard rule: the 3.7 gate is only green when a real
  `latexmk` exit-0 compile has run.

---

## 9. pipeline.yaml wiring

M3 fills the previously-reserved stage keys. The shipped default (permissive-only):

```yaml
version: 1
stages:
  ingest: pypdfium2            # PDF render + image load (BSD/Apache) — default
  layout: pp_doclayout_onnx    # PERMISSIVE Apache-2.0 default; born-digital pages use the
                               # structural text-layer fast-path automatically
  recognize:
    formula: pix2tex           # M2 default, reused unchanged (MIT)
    text: pp_ocrv5_onnx        # M3 default PP-OCRv5 (Apache-2.0); tesseract = permissive fallback
    # table / handwriting set in M6
  ensemble: null               # M5
  export: markdown             # default export target for the headline PDF→MD flow
ingest:                        # toggles + DPI live here (Pydantic-validated, no magic constants)
  base_dpi: 260
  max_dpi: 400
  small_font_px: 12
  preprocess: { deskew: true, denoise: true, binarize: false, perspective: false, auto_crop: true }
```

`pipeline_config.py` is extended: `Stages.ingest` / `Stages.layout` become live ids;
`RecognizeStage.text` is used; an `IngestConfig` block (DPI + preprocess toggles) is added to the
typed config. **Opt-in AGPL engines (`doclayout_yolo`, PyMuPDF) are never written as a default id
here** — they are only reachable through the explicit opt-in registration/acknowledgment path.

**M4-readiness:** the assembler takes one `RenderedPage` + bitmap and returns one `PageResult` with
no cross-page state, and the renderer yields pages lazily — so M4's streaming job runner calls
`assemble_page` per page, checkpoints the `PageResult` to SQLite, and frees the bitmap, achieving
constant memory with zero changes to M3 code.

---

## 10. Fixtures to add (`engine/tests/fixtures/`) — real data, no mocked OCR

| Fixture | Purpose | Tasks |
|---|---|---|
| `born_digital_math.pdf` | 1–2 page born-digital PDF with a title, a paragraph, one inline formula, and one **numbered display equation** across two columns on one page | 3.1, 3.3(born-digital), 3.4, 3.6, 3.7 |
| `scanned_page.png` | a rasterized page image (scanned-style) to exercise the model layout path + preprocessing + PP-OCRv5 | 3.1, 3.2, 3.3(model), 3.5 |
| `text_en.png` | cropped English text line/block | 3.5 (EN accuracy sanity) |
| `text_id.png` | cropped Indonesian text line/block (with ID-specific words/diacritics) | 3.5 (ID accuracy sanity) |
| `skewed_scan.png` + expected | small skewed image for the deskew before/after toggle test | 3.2 |
| `two_column.json` (region list) | synthetic region set for the reading-order unit test (pure, no image) | 3.4 |
| `inline_math_para.json` (region list w/ `inlines`) | fixed text block with text→math→text runs for the in-paragraph inline-math export test (F5) | 3.7 |
| `golden/doc_sample.md`, `golden/doc_sample.tex` | golden exports of a fixed in-test `DocumentResult` (includes the inline-math paragraph so `$...$` placement is byte-asserted) | 3.7 |

The born-digital PDF and the text crops are **real inputs** run through the **real** engines
(recognition path has no mocks, `R-REC-8`). Only the export goldens use a constructed
`DocumentResult` as deterministic *test input* (not a mocked production OCR result). The
`scripts/` synthetic-PDF generator (already referenced in `structure.md`) produces
`born_digital_math.pdf` reproducibly so the fixture is regenerable and license-clean.

---

## 11. Settings additions (`settings.py`, pydantic-settings)

New `TEXORA_ENGINE_`-prefixed / pipeline.yaml-backed values (all with defaults, no magic
constants): `ingest.base_dpi`, `ingest.max_dpi`, `ingest.small_font_px`,
`ingest.born_digital_char_threshold`, `ingest.born_digital_coverage`, the `PreprocessSettings`
block, `page.region_timeout_s`, `page.region_concurrency`, `recognize.text_fallback_to_tesseract`
(default true), `recognize.tesseract_cmd` (optional absolute path to the `tesseract` binary;
`None` → resolve on `PATH`), `recognize.tesseract_data_dir` (optional traineddata dir),
`export.preamble`, `export.figure_asset_dir`. Device (cpu/cuda/mps) reuses the existing M2
`settings.device` for the onnxruntime execution provider selection.

---

## 12. Error handling (concrete, per failing operation)

| Operation | Failure | Recoverable? | Caller receives | Logged |
|---|---|---|---|---|
| Open PDF (pypdfium2) | corrupt/encrypted/not-a-PDF | fatal for that doc | 422 (bad input) with reason | WARNING |
| Render a page | pdfium render error | recoverable (page-level) | page marked `failed` in `DocumentResult`; doc continues | WARNING w/ page idx |
| Load image | undecodable / bomb / oversize | fatal for that image | 422 per image | WARNING |
| Text-layer extract | pdfium text error | recoverable | fall back to treating page as scanned | INFO |
| Preprocess step | OpenCV raises | recoverable | skip that step, use prior image | WARNING |
| Layout detect | onnx/inference error | recoverable | `LayoutResult(regions=[])` → page `needs_review` | WARNING |
| Model not downloaded (`build_text_recognizer`) | `ModelNotReady` | recoverable | per the §7.2.1 table: Tesseract adapter if fallback enabled **and** Tesseract usable, else **409** (prompt download). The two outcomes are mutually exclusive branches of one decision — never both. | INFO (degrade) / — (409) |
| Tesseract selected/needed but binary missing | `TesseractUnavailable` | fatal for text stage | 409 with "install or point to Tesseract" message | WARNING |
| Model not downloaded (layout/formula) | `ModelNotReady` | recoverable | 409 (prompt download) | INFO |
| Text recognize | inference error/timeout | recoverable (region) | region `failed`, page continues | WARNING |
| Formula recognize | (M2 adapter already) | recoverable (region) | region `failed`/`needs_review` | WARNING (adapter) |
| LaTeX validate | invalid/unsupported macro | recoverable | region `needs_review`/`failed` (M2 logic) | — |
| MathML convert | latex2mathml raises | recoverable | `mathml=None`, latex kept (M2 logic) | WARNING |
| Markdown/LaTeX export | unexpected region shape | fatal for export call | 500 with context (should not happen; regions are typed) | ERROR |
| Path validation | path escapes allowed roots / traversal | fatal | 422, request rejected | WARNING |

Pipeline misconfiguration (unknown/absent stage id) raises the typed factory errors → **500 with a
clear message**, never a silent default — matching M2.

### 12.1 Input validation rules (per external input)

- **file path** — required for path-mode; must be an existing regular file under an allowed root,
  no `..` traversal, extension in the accepted set; else 422 (`R-SEC-3`).
- **uploaded image bytes** — ≤ byte/area/edge bounds (M2 guards reused); decodable; else 422.
- **page range** — optional; ints within `[0, page_count)`, `start ≤ end`; out-of-range → 422.
- **DPI override** — optional; clamped to `[72, max_dpi]`; invalid → 422.
- **preprocess toggles** — optional booleans; unknown keys ignored (`extra="ignore"`).
- **engine ids in pipeline.yaml** — validated by the factories at build time; unknown → 500 typed.

### 12.2 Invariants and their owning layer

- *No fabricated OCR* — owned by each adapter (`detect`/`recognize` return typed failed/empty) and
  re-asserted by the assembler status roll-up. Why: single enforcement point per boundary +
  defense-in-depth at assembly.
- *Reading order is total and deterministic* — owned by `reading_order.py` (pure). Why: testable in
  isolation; assembler trusts it.
- *Bitmap lifetime ≈ constant memory* — owned by the assembler (closes images) and the lazy
  renderer. Why: M4 streaming correctness.
- *Permissive-only default path* — owned by the factory registries (opt-in engines not registered)
  + `pipeline.yaml` + `docs/LICENSES.md`. Why: `R-LIC-2` must be unbreakable by config default.
- *Coordinate frame* (all bboxes in rendered-image pixels, top-left origin) — owned by
  `ingest/pdf.py` at the point of text-layer extraction. Why: one conversion site, unit-tested.

---

## 13. Testability (`R-QA-3`, >80% core coverage)

- **Unit (pure, real data):** DPI small-font raise logic; born-digital/scanned classifier;
  pdfium point→pixel coordinate conversion; each preprocess toggle (before/after); reading-order on
  the two-column + equation-number fixtures; the born-digital math heuristic; status roll-up.
- **Adapter tests (real fixtures, no mocks):** `pp_doclayout_onnx.detect` returns typed regions on
  `scanned_page.png`; `text_ppocr_onnx` + `text_tesseract` return sane text on `text_en.png` /
  `text_id.png`; failure injection (corrupt onnx session) → empty/failed, never raises.
- **Integration:** `assemble_page` on `born_digital_math.pdf` → `PageResult` whose structure
  matches expected (region types, reading order, one display equation with latex, one inline math),
  calling the real pix2tex + text engines.
- **Golden-file (exports):** `document_to_markdown` / `document_to_latex` byte-match the goldens
  (including a **paragraph-with-inline-math** golden proving `$...$` lands mid-paragraph, F5);
  `.tex` compiles under `latexmk` — **non-skippable in CI** (dedicated `m3-latex-compile` job
  provisions the TeX toolchain and asserts exit 0; local dev may xfail-skip, §8.3, F4).
- **API:** `POST /pages/recognize` returns 200 + `DocumentResult` on the fixture, 401 without
  token, 409 when a model is absent, 422 on a bad path.

A design note on hard-to-test surfaces: ONNX model inference is slow and weight-dependent, so
adapter tests are marked `@pytest.mark.model` and gated behind "weights present" (same pattern as
the M2 pix2tex test that asserts `ModelNotReady` without weights) — CI downloads the pinned weights
once and caches them, honoring the M2-approved real-network-fetch for model-backed tests.

---

## 14. Per-task `done:` criteria mapping

| Task | `done:` (from tasks.md) | How this design satisfies it |
|---|---|---|
| **3.1** | renders PDF + each image format; DPI auto-raise unit test | `ingest/pdf.py` + `ingest/images.py` (all formats incl. HEIC via pillow-heif); adaptive-DPI + one-shot small-font raise unit-tested |
| **3.2** | before/after fixtures; toggles respected | `ingest/preprocess.py` one pure fn per step, each flag-gated; `skewed_scan` before/after + toggle no-op tests |
| **3.3** | region types + bboxes on fixtures; license recorded | `layout/base.py` Protocol + `pp_doclayout_onnx` (PERMISSIVE default) + born-digital detector; full `RegionType` taxonomy + bbox + confidence; DocLayout-YOLO verdict AGPL→opt-in recorded in `docs/LICENSES.md` |
| **3.4** | multi-column fixture ordered correctly | `reading_order.py` XY-cut + column + equation-number binding; two-column + eq-number tests |
| **3.5** | text accuracy sanity EN + ID fixtures | `text_ppocr_onnx` (default) + `text_tesseract` (fallback), `langs=("en","id")`; `text_en.png`/`text_id.png` sanity tests |
| **3.6** | assembled JSON matches expected structure on fixture | `pipeline/assembler.py` → typed `PageResult`/`DocumentResult`, calling text + **reused M2 pix2tex**; integration test on `born_digital_math.pdf` |
| **3.7** | golden-file export; LaTeX compiles | `export/markdown.py` + `export/latex.py`; byte-stable golden `.md`/`.tex` incl. a paragraph-with-inline-math golden (true in-paragraph `$...$`, F5); **non-skippable CI `latexmk` exit-0 compile** of the golden `.tex` (F4) |

---

## 15. Out of scope for M3 (explicit)

- Job queue, per-page SQLite state machine, checkpoint/resume, 5,000-page proof → **M4**.
- Table recognition (SLANet), DOCX/OMML, searchable PDF, HTML/MathML/AsciiMath exporters,
  handwriting path → **M6** (tables/handwriting are *detected* in M3 and marked `needs_review`,
  never fabricated).
- Ensemble second-engine voting + full needs-review UI → **M5**.
- Benchmark-chosen final defaults (`pipeline.yaml` numbers are provisional until M7) → **M7**.
- Document Workspace split-view UI, confidence overlay → M5 UI (M3 ships the engine + API only).

---

## 16. `docs/LICENSES.md` rows to add in this change (`R-LIC-1`)

Runtime (permissive, default path): `pypdfium2` 5.14.0 (BSD-3-Clause/Apache-2.0),
`pillow-heif` 0.18.0 (BSD-3-Clause; libheif LGPL-3.0 dynamically linked), `onnxruntime` 1.19.x
(MIT), `pytesseract` 0.3.13 (Apache-2.0) + Tesseract 5.x (Apache-2.0),
`shapely`/`pyclipper` (BSD/MIT, PP-OCR postprocess transitive). ML models (file names pinned now
per §2.1; URL+SHA pin-on-first-fetch, mirroring the pix2tex honesty note): `pp_doclayout`
(`doclayout.onnx`, `label_map.txt` — Apache-2.0), `pp_ocrv5_det` (`det.onnx` — Apache-2.0),
`pp_ocrv5_rec` (`rec.onnx`, `rec_keys.txt` char dictionary — Apache-2.0). If an official stable
ONNX export URL is unavailable at adoption, the Apache-2.0 `rapid-layout` / `rapidocr-onnxruntime`
redistribution of the same PP model family is pinned instead (same license, same file-name
contract) — a documented contingency, not a silent fallback. Deferred/opt-in section:
**DocLayout-YOLO / doclayout-yolo 0.0.4 / ultralytics — AGPL-3.0 — opt-in only, never default, not
bundled** (verified 2026-10-18; re-confirm each license from the official source at adoption per
R-LIC-1, as the review's environment could not independently re-pull the classifiers).

---

## 17. Responses to the design review (`m3-design-review.{md,json}`)

Verdict under review: **CHANGES_REQUESTED** (5 MEDIUM, 2 NIT). Every finding is addressed below;
none is backlogged or ignored, because each was a concrete correctness/feasibility gap within M3's
own scope.

- **F1 (MEDIUM — multi-model resolution unspecified) — ADDRESSED.** New **§2.1** specifies the
  factories resolving **every** id in `entry.model_ids` via a dict-comprehension over
  `require_ready` (not just `model_ids[0]`), gives the exact constructor signature of each adapter
  (`PpOcrV5TextRecognizer(det_onnx, rec_onnx, dict_path, langs, device)`,
  `PpDocLayoutOnnxDetector(layout_onnx, label_map, device)`, `TesseractTextRecognizer(...)`), and
  enumerates every `ModelFile.name` each adapter requests. The PP-OCR **character dictionary**
  (`rec_keys.txt`) that was missing is now a pinned `ModelFile` on `pp_ocrv5_rec`.

- **F2 (MEDIUM — Tesseract fallback trigger under-specified + conflicts with 409) — ADDRESSED.**
  New **§7.2.1** places the single owning decision in `build_text_recognizer` (because
  `require_ready` raises `ModelNotReady` at build time, not recognize time), with a deterministic
  decision table: PP present → PP; PP absent + fallback on + Tesseract usable → Tesseract (INFO
  degrade, `engine_id` stamped); otherwise → **409**. "Tesseract usable" is defined (binary resolves
  + version probe). The §12 error table row is rewritten so the fallback and the 409 are mutually
  exclusive branches of one decision, removing the conflict.

- **F3 (MEDIUM — engine-id inconsistency; stable `id`s undeclared) — ADDRESSED.** New **§2.1** fixes
  each adapter's `id` verbatim (`pp_ocrv5_onnx`, `tesseract`, `pp_doclayout_onnx`, `doclayout_yolo`,
  `pix2tex`), ties `pipeline.yaml` values to them character-for-character, and adds a factory test
  asserting `build_*(...).id == configured id`. `born_digital` is explicitly not a registry id.

- **F4 (MEDIUM — LaTeX-compile gate skippable) — ADDRESSED.** **§8.3** and **§13** now make the
  compile check **non-skippable in CI**: a dedicated `m3-latex-compile` job provisions a minimal TeX
  toolchain (`latexmk` + texlive/TinyTeX) and asserts `latexmk` exit 0 on the golden `.tex`. Only
  local dev may xfail-skip; the 3.7 gate is green only after a real compile. §14 row 3.7 updated.

- **F5 (MEDIUM — in-paragraph inline math has no mechanism) — ADDRESSED (chose option a).** The
  `PageResult` model (**§7.3**) now carries `RegionContent.inlines: list[InlineRun]` (ordered
  `TEXT`/`MATH` runs). New **§6.5** specifies how the born-digital path (from per-span `is_mathish`)
  and the model path (inline-math sub-box containment) build that ordered run list, and **§6.4**
  defines intra-line run ordering. The exporters (**§8.1/§8.2**) concatenate runs so `$...$` lands at
  its true position in the paragraph. A new `inline_math_para` fixture + export golden byte-assert it.

- **F6 (NIT — catalog rows lack file names) — ADDRESSED.** **§2.1** and **§16** enumerate every
  `ModelFile.name` now (the hard `file_path(name)` contract); URL+SHA stay pin-on-first-fetch at
  adoption with the pix2tex-style honesty note.

- **F7 (NIT — `order(regions, page)` over-broad) — ADDRESSED.** **§6.4** changes the signature to
  `order(regions, width, height)` — the only page fields the thresholds need — keeping it a minimal
  pure function.

On the review's one "unverified" caveat (license strings could not be re-pulled in the review
environment): the design's **decision** is unchanged and correct — permissive Apache-2.0/BSD default
path, AGPL DocLayout-YOLO opt-in-only and unregistered. §16 now states explicitly that each license
must be re-confirmed from the official source at adoption (R-LIC-1), with the Apache-2.0
`rapid-layout`/`rapidocr-onnxruntime` contingency if a stable official ONNX export URL is missing.

