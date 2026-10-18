# M3 Implementation Plan — PDF → Markdown/LaTeX pipeline

Source of truth: the APPROVED design `.agents/tasks/m3-design.md` (v2, review APPROVED in
`.agents/tasks/m3-design-review.json`) and `.kiro/specs/texora/tasks.md` §M3 (tasks 3.1–3.7).
This plan sequences that design faithfully; it does not re-decide architecture.

## Absolute-path + environment contract (applies to EVERY item)

- Worktree root (all paths are ABSOLUTE under it; step agents default to the MAIN workspace cwd,
  so always pass the worktree path explicitly):
  `c:\data\kucing\texora\.worktrees\m3-pdf-pipeline`
- Git: always `git -C "c:\data\kucing\texora\.worktrees\m3-pdf-pipeline" ...`. Branch
  `feat/m3-pdf-pipeline` (already checked out). Conventional-commit messages, one focused commit
  per task. Do NOT merge, do NOT push.
- Prepend this PATH export before EVERY build/test/git shell command:
  ```bash
  export PATH="$HOME/.cargo/bin:$LOCALAPPDATA/Programs/Python/Python311:$LOCALAPPDATA/Programs/Python/Python311/Scripts:$LOCALAPPDATA/Microsoft/WinGet/Packages/pnpm.pnpm_Microsoft.Winget.Source_8wekyb3d8bbwe:$PATH"
  ```
- Engine venv for this worktree: `c:\data\kucing\texora\.worktrees\m3-pdf-pipeline\engine\.venv`
  (gitignored; created in item 1 — it does NOT yet exist in this worktree). Use its interpreter
  `engine\.venv\Scripts\python.exe` for all engine commands. Run engine commands from
  `c:\data\kucing\texora\.worktrees\m3-pdf-pipeline\engine`.
- Engine gate after every engine-touching item (all must pass before the item is done):
  ```bash
  .venv/Scripts/python.exe -m ruff check .
  .venv/Scripts/python.exe -m black --check . --line-length 100
  .venv/Scripts/python.exe -m mypy texora_engine
  .venv/Scripts/python.exe -m pytest -q
  ```
- Honesty / license rules (from steering): NO mocked OCR in production paths; a region that cannot
  be recognized is `needs_review`/`failed`, never guessed. Each NEW dependency or model gets a
  `docs/LICENSES.md` row in the SAME change. Permissive-first: the default layout engine is the
  Apache-2.0 `pp_doclayout_onnx` + the no-model born-digital fast-path; DocLayout-YOLO is AGPL →
  opt-in only, NOT registered in the default factory, NOT a default id in `pipeline.yaml`.

## HOST LIMITATIONS to flag (document as PENDING, never claim done)

- **No TeX toolchain on this host** (`latexmk` absent — verified during planning). The design
  (§8.3, F4) makes the `latexmk` exit-0 compile NON-skippable *in CI* but allows **local dev to
  xfail-skip** when no TeX toolchain is found. So on THIS host the golden `.tex` is byte-asserted
  and structurally validated, and the real `latexmk` compile is recorded in `docs/m3-verification.md`
  as PENDING (CI job `m3-latex-compile` provisions TinyTeX/texlive and runs it). The compile test
  is marked `@pytest.mark.latex` and xfail-skips locally; it must NOT be deleted or silently passed.
- **ONNX model weights** for `pp_doclayout` / `pp_ocrv5_det` / `pp_ocrv5_rec`: real URLs + SHA-256
  are pin-on-first-fetch at adoption (mirrors the pix2tex honesty note). Model-backed adapter tests
  are `@pytest.mark.model` and skip-with-reason when weights are absent (same gate as the M2 pix2tex
  real-model test) — never mocked. If a stable official ONNX export URL cannot be confirmed at
  adoption, pin the Apache-2.0 `rapid-layout`/`rapidocr-onnxruntime` redistribution (same license +
  file-name contract) and record it in `docs/LICENSES.md` + `docs/m3-verification.md`.
- **GPU (CUDA) execution provider** is unverifiable on this CPU host; onnxruntime CPU EP is the
  tested path. CUDA EP wiring is code-reviewed only and flagged PENDING.

---

- [ ] 1. **Environment + dependency pins + license rows (foundation for every later item).**
      Create the M3 engine venv and install the pinned M3 runtime deps on top of the M2 stack;
      add every new dependency to `engine/requirements.txt` and a matching row to `docs/LICENSES.md`
      in this same change. New runtime pins (verify each exact version against official PyPI metadata
      before install; adjust to nearest existing patch in the same minor if a patch is unavailable,
      and record the actual installed version): `pypdfium2==5.14.0` (BSD-3-Clause/Apache-2.0),
      `pillow-heif==0.18.0` (BSD-3-Clause; bundled libheif LGPL-3.0, dynamically linked),
      `onnxruntime==1.19.*` (MIT), `pytesseract==0.3.13` (Apache-2.0), plus PP-OCR ONNX post-process
      transitives `shapely` + `pyclipper` (BSD/MIT) only if the chosen ONNX text path needs them.
      `opencv-python-headless` + `numpy` are already pinned (M2) — reuse, do not re-add. Add
      `@pytest.mark.model` and `@pytest.mark.latex` markers to `engine/pyproject.toml` or
      `engine/pytest.ini` (whichever the repo uses) so they are registered (no unknown-marker
      warnings). Add the "Deferred / opt-in only" `docs/LICENSES.md` row for **DocLayout-YOLO /
      doclayout-yolo 0.0.4 / ultralytics — AGPL-3.0 — opt-in only, never default, not bundled**
      (re-confirm the classifier from the official source at adoption).
      Files: `c:\data\kucing\texora\.worktrees\m3-pdf-pipeline\engine\requirements.txt`,
      `...\engine\requirements-dev.txt` (if the latex/model test markers or any dev tool needs it),
      `...\docs\LICENSES.md`, and the pytest marker registration file under `...\engine\`.
      Verify: create the venv and install, then confirm no broken deps and import smoke —
      ```bash
      cd engine
      py -3.11 -m venv .venv    # or the Python 3.11 launcher available on this host
      .venv/Scripts/python.exe -m pip install -r requirements-dev.txt --extra-index-url https://download.pytorch.org/whl/cpu
      .venv/Scripts/python.exe -m pip check
      .venv/Scripts/python.exe -c "import pypdfium2, PIL, pillow_heif, onnxruntime, pytesseract, cv2, numpy; print('ok')"
      ```
      Expected: `No broken requirements found.` and `ok`. Then the full engine gate (ruff/black/mypy/
      pytest) still passes (M2 suite unchanged). Commit: `chore(engine): pin M3 ingest/layout/text deps + license rows`.

- [ ] 2. **Config scaffolding: pipeline.yaml stages + typed IngestConfig + settings (3.1–3.7 prereq).**
      Extend `pipeline_config.py` so `Stages.ingest`/`Stages.layout` are live ids, `RecognizeStage.text`
      is used, `stages.export` is set, and add a typed `IngestConfig` block (base_dpi/max_dpi/
      small_font_px/born_digital_char_threshold/born_digital_coverage + a nested `PreprocessSettings`
      with deskew/denoise/binarize/perspective/auto_crop). pipeline.yaml is the source of truth for
      ingest values, mirrored into settings (resolves design N5). Fill `pipeline.yaml` with the
      design §9 default block (`ingest: pypdfium2`, `layout: pp_doclayout_onnx`,
      `recognize.text: pp_ocrv5_onnx`, `export: markdown`, the `ingest:` toggles). Add the new
      `TEXORA_ENGINE_`-backed settings in `settings.py` (region_timeout_s, region_concurrency,
      text_fallback_to_tesseract=true, tesseract_cmd, tesseract_data_dir, export.preamble,
      export.figure_asset_dir). No magic constants in code.
      Files: `...\engine\texora_engine\pipeline_config.py`, `...\engine\texora_engine\settings.py`,
      `...\pipeline.yaml`, and extend `...\engine\tests\test_pipeline_config.py` +
      `...\engine\tests\test_settings.py`.
      Verify: `cd engine && .venv/Scripts/python.exe -m pytest tests/test_pipeline_config.py tests/test_settings.py -q`
      — new assertions (ingest/layout/text ids load from real yaml; IngestConfig defaults; preprocess
      toggles parse) pass; then the full engine gate. Commit: `feat(engine): wire M3 pipeline.yaml stages + typed ingest/settings config`.

- [ ] 3. **Task 3.1 — pypdfium2 ingestion + image loaders + born-digital/scanned detection.**
      Create the `ingest/` package: `base.py` typed models (`SourceKind`, `PdfTextSpan`,
      `RenderedPage` — JSON-serializable, no bitmap on the model); `pdf.py` pypdfium2 renderer with
      adaptive DPI and the one-shot small-font raise (re-render once when
      `median_span_font_pt * base_dpi / 72 < small_font_px`, resolves design N1) plus pdfium text-layer
      extraction converting pdfium point coords (bottom-left, 72dpi) to rendered-image pixels
      (top-left, effective DPI) — this is the single coordinate-frame site, unit-tested; `images.py`
      Pillow + pillow-heif loaders (PNG/JPG/JPEG/WEBP/BMP/TIFF multi-frame/HEIC) reusing the M2
      decompression-bomb guards; `detect.py` pure per-page born-digital-vs-scanned classifier using
      the design thresholds. Add the real fixtures. Lazy page iteration; bitmaps freed promptly.
      Files: `...\engine\texora_engine\ingest\__init__.py`, `...\ingest\base.py`, `...\ingest\pdf.py`,
      `...\ingest\images.py`, `...\ingest\detect.py`; fixtures `...\engine\tests\fixtures\born_digital_math.pdf`
      (generated reproducibly — add/extend `...\scripts\` synthetic-PDF generator; title + paragraph +
      one inline formula + one numbered display equation, two-column on one page), `...\fixtures\scanned_page.png`,
      `...\fixtures\text_en.png`, `...\fixtures\text_id.png`; tests `...\engine\tests\test_ingest_pdf.py`,
      `...\test_ingest_images.py`, `...\test_ingest_detect.py`.
      Done-check (tasks.md 3.1): renders PDF + each image format; DPI auto-raise unit test.
      Verify: `cd engine && .venv/Scripts/python.exe -m pytest tests/test_ingest_pdf.py tests/test_ingest_images.py tests/test_ingest_detect.py -q`
      — renders the fixture PDF to a PIL image at the expected size, loads each image format incl.
      HEIC, the small-font raise re-renders exactly once, the point→pixel conversion matches the known
      fixture, and the classifier is positive on the born-digital PDF / negative on the scanned image.
      Then full engine gate. Commit: `feat(engine): pypdfium2 ingestion, image loaders, born-digital detection (3.1)`.

- [ ] 4. **Task 3.2 — preprocessing (deskew/denoise/binarize/perspective/auto_crop, each toggleable).**
      Add `ingest/preprocess.py`: one pure function per step, each flag-gated by `PreprocessSettings`
      (binarize + perspective default off), applied in the fixed order deskew→perspective→denoise→
      binarize→auto_crop, each returning a new image with the previous freed; born-digital pages
      default to no preprocessing unless forced. A disabled step is a no-op; an enabled step changes
      pixels in the expected direction (deskew reduces measured skew).
      Files: `...\engine\texora_engine\ingest\preprocess.py`; fixtures
      `...\engine\tests\fixtures\skewed_scan.png` (+ an expected/metadata companion for the before/after
      assertion); test `...\engine\tests\test_preprocess.py`.
      Done-check (tasks.md 3.2): before/after fixtures; toggles respected.
      Verify: `cd engine && .venv/Scripts/python.exe -m pytest tests/test_preprocess.py -q`
      — each toggle false → output pixels identical to input (no-op); deskew true on `skewed_scan.png`
      → measured skew angle drops below threshold. Then full engine gate.
      Commit: `feat(engine): toggleable image preprocessing (3.2)`.

- [ ] 5. **Task 3.3 — layout Protocol + factory + permissive default detector(s); license recorded.**
      Add `layout/base.py` (the `LayoutDetector` Protocol + `RegionType` full taxonomy, `BBox`,
      `Region` with confidence + reading_order + source, `LayoutResult`; `detect` catches its own
      errors and returns `regions=[]`, never raises). Add `layout/factory.py` mirroring
      `recognizers/factory.py` with a permissive-only `_REGISTRY` (resolves EVERY id in
      `entry.model_ids` via a dict-comprehension over `require_ready`, per design §2.1), typed
      `LayoutStageNotConfigured`/`UnknownLayoutEngineError`. Add `layout/born_digital.py` (no model,
      not a registry id — assembler-owned structural detector from the pdfium text layer, including
      the minimal `is_mathish` signal set from design N2: math Unicode-block ratio, italic/math-font
      flag, line isolation, right-margin `(n)`). Add `layout/pp_doclayout_onnx.py` (id
      `pp_doclayout_onnx`, `model_ids=("pp_doclayout",)`, onnxruntime CPU EP default / CUDA EP when
      `settings.device=="cuda"`; decode boxes to Regions via `label_map.txt`). Add
      `layout/doclayout_yolo.py` (id `doclayout_yolo`, AGPL) but DO NOT register it in `_REGISTRY`.
      Add the catalog rows for `pp_doclayout`/`pp_ocrv5_det`/`pp_ocrv5_rec` with the exact
      `ModelFile.name`s from design §2.1 (URL+SHA pin-on-first-fetch) and the matching `docs/LICENSES.md`
      rows (ML models section + the AGPL opt-in row from item 1 if not already present).
      Files: `...\engine\texora_engine\layout\__init__.py`, `...\layout\base.py`, `...\layout\factory.py`,
      `...\layout\born_digital.py`, `...\layout\pp_doclayout_onnx.py`, `...\layout\doclayout_yolo.py`;
      `...\engine\texora_engine\models\catalog.py` (add 3 specs); `...\docs\LICENSES.md`;
      tests `...\engine\tests\test_layout_base.py`, `...\test_layout_factory.py`,
      `...\test_layout_born_digital.py`, `...\test_layout_ppdoclayout.py` (model-gated,
      `@pytest.mark.model`, skip-with-reason if weights absent; failure-injection → empty LayoutResult,
      never raises).
      Done-check (tasks.md 3.3): region types + bboxes on fixtures; license recorded (AGPL verdict →
      opt-in, unregistered).
      Verify: `cd engine && .venv/Scripts/python.exe -m pytest tests/test_layout_base.py tests/test_layout_factory.py tests/test_layout_born_digital.py -q`
      — the factory builds `pp_doclayout_onnx` and its `.id` equals the configured id, `doclayout_yolo`
      is NOT in `known` ids, unknown id raises the typed error; born_digital detector yields typed
      Regions with bboxes + types on the born-digital fixture. Model-backed test runs when weights are
      prefetched, else skips with reason. Then full engine gate.
      Commit: `feat(engine): layout Protocol + permissive default detector + AGPL opt-in gate (3.3)`.

- [ ] 6. **Task 3.4 — reading order (XY-cut + columns + equation-number binding + intra-line runs).**
      Add `layout/reading_order.py` with the pure `order(regions, width, height) -> list[Region]`
      (resolves design F7): column detection via x-center projection + gutters, recursive XY-cut for
      global top-to-bottom/left-to-right, right-margin `EQUATION_NUMBER` attached to its nearest
      `DISPLAY_MATH` on the same band, headers/footers ordered out-of-band. Intra-block inline-run
      ordering (text→math→text within a line) is produced by the detector's run list; document the
      two-level ordering (block int + run list) per design §6.4/§6.5.
      Files: `...\engine\texora_engine\layout\reading_order.py`; fixtures
      `...\engine\tests\fixtures\two_column.json` (synthetic region set, no image),
      `...\fixtures\inline_math_para.json` (text block with text→math→text runs); test
      `...\engine\tests\test_reading_order.py`.
      Done-check (tasks.md 3.4): multi-column fixture ordered correctly.
      Verify: `cd engine && .venv/Scripts/python.exe -m pytest tests/test_reading_order.py -q`
      — the two-column fixture yields the correct interleaved top-to-bottom reading order, the
      display-equation + right-number fixture binds the number to its equation, and the inline-math
      paragraph orders runs text→math→text. Then full engine gate.
      Commit: `feat(engine): XY-cut reading order with column + equation-number handling (3.4)`.

- [ ] 7. **Task 3.5 — text recognizer Protocol + PP-OCRv5 default + Tesseract fallback (EN + ID).**
      Add the `TextRecognizer` Protocol + `TextLine`/`TextResult` to `recognizers/base.py` (reuse M2
      `RecognitionStatus`/`ConfidenceKind`/`RegionContext`/`BBox`). Add `recognizers/text_factory.py`
      mirroring the formula/layout factories, implementing the single-owning fallback decision in
      `build_text_recognizer` exactly per design §7.2.1 (PP present → PP; `ModelNotReady` + fallback
      on + Tesseract usable → Tesseract INFO-logged degrade; else raise → 409; explicit `tesseract`
      with missing binary → `TesseractUnavailable`). Add `recognizers/text_ppocr_onnx.py` (id
      `pp_ocrv5_onnx`, `model_ids=("pp_ocrv5_det","pp_ocrv5_rec")`, `langs=("en","id")`, onnxruntime,
      real per-line confidence, decode via `rec_keys.txt`; inference error → `status=FAILED`, never a
      guess) and `recognizers/text_tesseract.py` (id `tesseract`, `model_ids=()`,
      `pytesseract.image_to_data` with `lang="eng+ind"`, per-word conf normalized 0–1).
      Files: `...\engine\texora_engine\recognizers\base.py`, `...\recognizers\text_factory.py`,
      `...\recognizers\text_ppocr_onnx.py`, `...\recognizers\text_tesseract.py`; tests
      `...\engine\tests\test_text_factory.py` (fallback decision table incl. the 409 branch,
      monkeypatching `_tesseract_available`), `...\test_text_ppocr.py` + `...\test_text_tesseract.py`
      (real fixtures `text_en.png`/`text_id.png`, model/binary-gated, skip-with-reason when absent;
      failure injection → FAILED, never raises).
      Done-check (tasks.md 3.5): text accuracy sanity test EN + ID fixtures.
      Verify: `cd engine && .venv/Scripts/python.exe -m pytest tests/test_text_factory.py tests/test_text_ppocr.py tests/test_text_tesseract.py -q`
      — the fallback decision table resolves deterministically (each row), the built adapter's `.id`
      matches the configured id, and on `text_en.png`/`text_id.png` the available engine returns
      non-empty sane text (EN + ID) when weights/binary are present (else skip-with-reason). Then full
      engine gate. Commit: `feat(engine): PP-OCRv5 text recognizer + Tesseract fallback, EN+ID (3.5)`.

- [ ] 8. **Task 3.6 — page assembler + typed PageResult/DocumentResult + POST /pages/recognize.**
      Create `pipeline/` package: `page_result.py` (the `RunKind`/`InlineRun`/`RegionContent`/
      `PageResult`/`DocumentResult` Pydantic models from design §7.3, including `inlines` for true
      in-paragraph inline math, resolves F5) and `assembler.py` implementing `assemble_page(rendered,
      image, deps) -> PageResult` per design §7.4: preprocess → layout (born-digital structural path
      for born-digital pages, else configured detector) → reading order → per-region recognition
      (text-ish regions build the ordered `inlines` run list; INLINE_MATH/DISPLAY_MATH crops ALWAYS
      re-recognized via the reused M2 `build_formula_recognizer` → `validate_and_normalize` →
      `latex_to_mathml`; TABLE/HANDWRITING → `needs_review` with a detail, never fabricated; FIGURE
      crop saved) → worst-of status roll-up → free the bitmap. `RegionContext(... source="page")`
      per region (design N4). Per-region timeout via the single-worker executor pattern (design §7.5).
      `PipelineDeps` bundles the built layout/text/formula engines (cached on `app.state`). Add
      `api/pages.py` `POST /pages/recognize` (bearer-protected `protected_router` pattern; path
      sanitize + page-range/DPI validation; ModelNotReady→409, misconfig→500, bad input/path→422) and
      mount it in `app.py`.
      Files: `...\engine\texora_engine\pipeline\__init__.py`, `...\pipeline\page_result.py`,
      `...\pipeline\assembler.py`, `...\engine\texora_engine\api\pages.py`,
      `...\engine\texora_engine\api\__init__.py` (export the new router), `...\engine\texora_engine\app.py`;
      tests `...\engine\tests\test_assembler.py` (integration on `born_digital_math.pdf` via the REAL
      pix2tex + text engines — model-gated, skip-with-reason when weights absent, never mocked; asserts
      region types, reading order, one display equation with latex, one inline-math run) and
      `...\test_pages_api.py` (200 + DocumentResult on the fixture; 401 without token; 409 when a model
      is absent; 422 on a bad path/range).
      Done-check (tasks.md 3.6): assembled JSON matches expected structure on fixture.
      Verify: `cd engine && .venv/Scripts/python.exe -m pytest tests/test_assembler.py tests/test_pages_api.py -q`
      — the assembled `PageResult`/`DocumentResult` structure matches the expected region types +
      reading order + inline-math placement on the fixture (model-gated path runs when weights are
      prefetched; otherwise the API error-mapping + structure tests still pass and the real-engine test
      skips with reason). Then full engine gate.
      Commit: `feat(engine): page assembler + PageResult model + POST /pages/recognize (3.6)`.

- [ ] 9. **Task 3.7 — Markdown + LaTeX exporters + golden files (LaTeX compile gated).**
      Add `export/markdown.py` (`document_to_markdown`: titles → `#`/`##`; paragraphs concatenate
      `inlines` so `$...$` lands mid-paragraph; `DISPLAY_MATH` → `$$...$$` with `\tag{n}` for attached
      numbers; lists/code; TABLE → honest `<!-- table: needs_review (M6) -->` placeholder; FIGURE →
      `![...](assets/...)`; `status!=ok` → `<!-- needs_review: ... -->` marker) and `export/latex.py`
      (`document_to_latex`: preamble template `article` default with amsmath/amssymb/graphicx/booktabs;
      `\section`/paragraph-inline/`equation`/`equation*`; needs_review → `% comment`). Options from
      settings/pipeline.yaml. Golden-file tests from a fixed in-test `DocumentResult` (test data, not
      mocked OCR), including the inline-math paragraph so `$...$` placement is byte-asserted. The
      `latexmk` exit-0 compile is `@pytest.mark.latex`: on THIS host (no TeX toolchain) it xfail-skips
      locally and is recorded PENDING in `docs/m3-verification.md`; the CI `m3-latex-compile` job
      provisions TinyTeX/texlive and asserts exit 0 — do NOT delete or silently pass the test.
      Files: `...\engine\texora_engine\export\markdown.py`, `...\export\latex.py`,
      `...\engine\texora_engine\export\__init__.py` (export the new emitters); golden fixtures
      `...\engine\tests\golden\doc_sample.md`, `...\golden\doc_sample.tex`; test
      `...\engine\tests\test_export_markdown.py`, `...\test_export_latex.py` (byte-match goldens +
      the inline-math placement assertion + the gated `latexmk` compile).
      Done-check (tasks.md 3.7): golden-file export; LaTeX compiles (compile NON-skippable in CI;
      local xfail-skip recorded PENDING here).
      Verify: `cd engine && .venv/Scripts/python.exe -m pytest tests/test_export_markdown.py tests/test_export_latex.py -q`
      — `document_to_markdown`/`document_to_latex` byte-match the goldens and the inline-math paragraph
      golden proves `$...$` lands mid-paragraph; the `latexmk` test xfail-skips on this host with a
      recorded reason (and would assert exit 0 where a toolchain exists). Then full engine gate.
      Commit: `feat(engine): Markdown + LaTeX exporters with golden files (3.7)`.

- [ ] 10. **Docs: PROGRESS.md + tasks.md ticks + docs/m3-verification.md with REAL output.**
      Update `docs/PROGRESS.md` to M3 state (branch `feat/m3-pdf-pipeline`, per-task status table,
      host-pending items). Tick `[x]` for 3.1–3.7 in `.kiro/specs/texora/tasks.md` ONLY for criteria
      actually met on this host (record anything host-limited as a note, never a false tick). Create
      `docs/m3-verification.md` mirroring `docs/m2-verification.md`: paste REAL command output for the
      engine gate (ruff/black/mypy/pytest) and the per-task test runs, include a sample
      PDF→Markdown result snippet produced from `born_digital_math.pdf` through the real pipeline, and
      record the LaTeX-compile + ONNX-model + CUDA items honestly as PENDING MANUAL/CI where they
      cannot run on this host.
      Files: `...\docs\PROGRESS.md`, `...\.kiro\specs\texora\tasks.md`, `...\docs\m3-verification.md`.
      Verify: re-run the full engine gate once more and confirm the pasted output in
      `docs/m3-verification.md` matches the live run; `git -C "<worktree>" status` shows only intended
      files. Commit: `docs(m3): progress + verification log + task ticks`.

## Notes / assumptions

- The M3 deliverable is ENGINE-SIDE. Do NOT block M3 on building the Tauri `externalBin` sidecar or
  launching the window — the sidecar binary is gitignored/absent in this worktree. M3 is verified via
  the engine venv pytest suite + the `POST /pages/recognize` TestClient tests, exactly as the step
  prompt requires.
- Model-backed tests follow the established M2 pattern: `@pytest.mark.model`, read prefetched weights
  from a models dir (extend `conftest.prefetched_models_dir` to cover the new ONNX models), and
  skip-with-reason when absent — never mocked. Add the ONNX weight-prefetch note to
  `docs/m3-verification.md`.
- Every item leaves the engine buildable and the full gate green; later items depend on earlier ones
  strictly in the order above (1→2→3→…→10).
