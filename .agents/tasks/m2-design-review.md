# M2 Formula-OCR Design Review — RELAUNCH convergence pass (v4)

Reviewer: design-review subagent (fresh read, no authoring context).
Target: `.worktrees/m2-formula-ocr/.agents/tasks/m2-design.md` (v4).
Prior gate: `.agents/tasks/m2-salvage/m2-design-review-v3.md` (v3 — CHANGES_REQUESTED: 1 HIGH, 3 MEDIUM, NITs).

## Scope of this pass (narrow by instruction)

This is a convergence review of ONLY the four user-settled resolutions that were in scope for the
relaunch, plus the cheap NITs and the two spec errata. Items the v3 review marked PASS (adapter
Protocol + factory wiring, no-mock/honesty, token-on-every-route, SQLite-through-`db/`,
single-typed-client, i18n id/en parity, host/interactive pending items, no invented benchmark
numbers, the JS→engine transport Decision 0) are **not** re-litigated here. I confirmed each of the
four resolutions is reflected in the v4 document and spot-checked the one independently verifiable
claim the NIT fix hinges on (`pipeline.yaml` placeholder shape).

Verdict: **APPROVED** (0 HIGH, 0 MEDIUM; 1 NIT, non-blocking). All four resolutions and all three
NITs are satisfactorily reflected, and the two errata stay flagged rather than silently applied.

---

## Resolution checklist

### Resolution 1 — Default model pix2tex + pin-on-first-fetch SHA-256 — REFLECTED

Where: §B.2 stack table, §B.3 ("SHA-256 pinning story — DECISION: pin-on-first-fetch…", adoption
checklist), FR-1, AC-1/AC-2, v4 response §1.

All five required elements are present and concrete:
- **Bypass pix2tex's auto-downloader.** §B.3 step 1 and §B.4 adapter both state the adapter
  **always** constructs pix2tex with explicit registry-resolved local checkpoint/resizer paths and
  **never** invokes the default-arg path that triggers the fetcher; a unit test asserts
  constructing with weights absent raises `ModelNotReady` and makes **no network call** (networking
  stubbed to fail). Covers R-SEC-1 + FR-1.
- **Fetch via our `models/` registry from the immutable per-tag release-asset URL.** §B.3 step 2 +
  the adoption checklist require the direct, non-redirecting, per-tag GitHub release-asset URL
  (explicitly "not `latest`, not a rolling/redirecting URL"), recorded per file in `catalog.py`.
- **Compute + record our own SHA-256 in `catalog.py`.** §B.3 step 3 and v4 response §1 both state
  the coder downloads once, computes the SHA-256 **ourselves**, and bakes the real value into
  `catalog.py`.
- **Verify every load + offline import.** §B.3 step 4: every subsequent load and every
  offline-bundle import re-verifies against the recorded hash; a mismatch rejects (AC-1/AC-2). The
  offline-bundle path is explicitly the no-network install path verifying the **same** recorded
  hash — "not a best-effort fallback" — which closes the exact v3 HIGH gap (auto-download degrading
  to best-effort).
- **Honesty caveat documented.** §B.3 states plainly the recorded checksum is our hash of the
  upstream asset, not a vendor-signed checksum, surfaced in `docs/LICENSES.md` (pix2tex model row)
  and `docs/m2-verification.md`, with vendor-pinned/HF-revision noted as an M7 option.
- **Coder computes the REAL hash, never invents one.** Stated emphatically in §B.3 step 3 and the
  adoption checklist ("confirm and record, never invent"), and again in v4 response §1. If the real
  URL/tag/filenames differ, the coder updates `ModelSpec`/`ModelFile`/`catalog.py`/`file_path(...)`
  to the real shape.

This fully resolves v3 Finding 1 (HIGH). The distribution feasibility is no longer "deferred/
best-effort"; the primary path is our registry-driven fetch with pin-on-first-fetch, and the import
path is first-class.

### Resolution 2 — Confidence contract asserted BOTH ways in AC-6 — REFLECTED

Where: AC-6, §B.4 "Confidence derivation", FR-4, v4 response §2.

AC-6 now asserts both branches explicitly:
- scores available → `confidence ∈ (0,1]` with `confidence_kind == "token_logprob"`;
- scores unavailable → `confidence == 0.0` with `confidence_kind == "unavailable"` **and** the Snip
  popup renders a "confidence unavailable" state **asserted in vitest**.

The provisional-default/M7 sentence is present verbatim in both AC-6 and v4 response §2 ("shipping
`"unavailable"` is an accepted, documented R-REC-2 satisfaction for the provisional M2 default; M7's
benchmark-chosen engine is expected to restore a numeric score"). The integration test asserts
whichever branch the pinned package yields (recorded in `docs/m2-verification.md`), and §B.4
reiterates no fabricated confidence ("what is not acceptable is implying a working logprob path that
may not exist"). The UI assertion is mirrored in §B.11 (`SnipPopup.tsx` shows "confidence
unavailable" when `confidenceKind === 'unavailable'`) and the i18n key `snip.confidenceUnavailable`
is enumerated. This resolves v3 Finding 2 (MEDIUM).

### Resolution 3 — KaTeX allow-list generator input + verified fallback — REFLECTED

Where: §B.6 "Allow-list provenance", FR-3, AC-5, `scripts/gen_katex_allowlist.py`, v4 response §3.

The generator input is specified precisely and no longer assumes the npm dist ships
`src/functions`/`src/macros`:
- **Primary** — parse the supported functions from the installed package's public API / shipped
  `katex.mjs` function registry (dist-only, no source tarball needed).
- **Verified fallback** — if the npm dist does not expose the support tables parseably, vendor the
  pinned `katex` **source** tarball (devDependency-only input) and parse `src/functions`/`src/macros`,
  **recording the tarball's SHA-256** (same pin-at-adoption discipline as the model).
- The exact input path is confirmed against the installed `katex@0.16.11` at implementation time and
  recorded in `docs/m2-verification.md`. The generated JSON carries a header recording the katex
  version (and, in the fallback path, the source-tarball SHA); a test asserts the recorded version
  matches the `katex` pin in `apps/desktop/package.json` so a bump without regeneration fails CI.

AC-5's "generated, cannot drift" property is explicitly preserved ("no hand-typed list masquerading
as generated"), and the acceptance boundary (allow-list false positive only downgrades to
`needs_review`; the real-`katex` vitest render is the sole correctness gate) is intact. This
resolves v3 Finding 3 (MEDIUM).

### Resolution 4 — ModelProgress Pydantic + mirrored TS + polling contract + per-file/overall bytes — REFLECTED

Where: §B.2b (new section), FR-1, §B.11, Part C file map, v4 response §4.

- **Pydantic model** — §B.2b defines `ModelDownloadState` (StrEnum:
  `downloading|verifying|ready|corrupt|error`), `ModelFileProgress` (`name`, `received`, `total`),
  and `ModelProgress` (`id`, `state`, `bytes_received`, `bytes_total`, `files`, `detail?`) in
  `engine/texora_engine/models/progress.py`, returned by `GET /models/{id}`.
- **Mirrored TS type** — the matching camelCase TS interfaces (`ModelDownloadState`,
  `ModelFileProgress`, `ModelProgress`) are defined in the `engineClient.ts` shared-types block.
- **Supervisor polling contract** — start (`model_download(id)` registers the id with the
  supervisor's in-flight poller map keyed by model id), **interval (fixed 500 ms)**, and **terminal
  stop condition** (stop + emit once more on `ready`/`corrupt`/`error`; `verifying` is non-terminal
  and keeps polling; engine-unreachable surfaces `error` and stops) are all specified. Reuses the
  existing `ureq` agent, runs alongside the health loop.
- **Per-file + overall bytes** — explicitly satisfied: `files[].received/total` per file;
  `bytes_received/bytes_total` overall rollup, matching FR-1's "per file AND overall".

This resolves v3 Finding 4 (MEDIUM).

### NITs — all three applied

- **pipeline.yaml full placeholder replacement + permissive-first comment** — §B.4 instructs
  replacing the ENTIRE commented placeholder body (including `# version: 1` and the flat `recognize:`
  comment) with the real config, and keeps a permissive-first comment in the new block. I
  independently verified the committed `pipeline.yaml` is fully commented with `recognize` as a
  single flat key — the before-state the design describes is accurate, so the replacement instruction
  is correctly grounded (resolves v3 NIT Finding 5).
- **factory adapter-declared `model_ids`** — the Protocol declares `model_ids: tuple[str, ...]`, the
  pix2tex adapter sets `model_ids = ("pix2tex",)`, and the factory resolves via `ctor.model_ids[0]`
  rather than assuming `adapter.id == model.id` (resolves v3 NIT Finding 6).
- **Pillow decode errors → 422 not 500** — §B.7 narrative (guard step 1) and the input-validation
  table both state `UnidentifiedImageError`/`DecompressionBombError`/any Pillow decode exception is
  caught and returned as 422 with a field detail, never a 500 (resolves v3 NIT Finding 7).

### Spec errata — kept FLAGGED, not silently applied

- **tasks.md 2.2 names PP-FormulaNet-S** as the provisional default. §B.3 and the v4 "Kept flagged"
  block flag that pix2tex supersedes it for M2 and that tasks.md should be updated by the spec owner;
  it is explicitly "not applied here."
- **R-REC-6 "render check (KaTeX)"** wording. §B.6 and the v4 "Kept flagged" block flag this as an
  erratum (engine does a macro-surface allow-list check; the authoritative real-`katex` render lives
  in vitest/UI), flagged to the spec owner rather than edited into the spec.

Both remain flagged in the dedicated "Kept flagged, NOT silently applied" block — correct handling.

---

## Findings

### Finding 1 — NIT — ModelProgress TS mirror omits the `verifying` → UI story, and the terminal set in the two type definitions is consistent but the client-side close trigger is only loosely stated

Where: §B.2b (`subscribeModelProgress` paragraph), §B.11 (`subscribeModelProgress` wrapper).

The `ModelProgress` payload and polling contract are fully pinned, and §B.2b says the first-run UI
"closes on a terminal state." That is sufficient for implementation. The only soft spot is that the
client-side terminal set is described prose-only ("closes on a terminal state") rather than naming
the three terminal literals (`ready`/`corrupt`/`error`) at the UI layer the way the supervisor stop
condition does. Since `ModelDownloadState` is a shared enum and the supervisor stop condition already
enumerates the terminal set, an implementer cannot reasonably diverge — hence NIT, not blocking.

Concrete fix (optional): in §B.11 state "the progress UI treats `ready|corrupt|error` as terminal
(same set as the supervisor stop condition) and renders the final state, then closes/offers retry,"
so the UI terminal set is named rather than implied.

---

## Verified Assumptions (checked this pass)

- **Committed `pipeline.yaml` is a fully-commented placeholder with `recognize` as a single flat key.**
  CONFIRMED by reading `c:\data\kucing\texora\pipeline.yaml` — every line commented, including
  `# version: 1`, and `recognize: # text / formula / table / handwriting` as one flat key. The
  design's described before-state and the "replace the ENTIRE commented body" NIT instruction are
  accurate.
- **All four resolutions are present in both the body (§B.2b/§B.3/§B.4/§B.6/AC-5/AC-6/FR-1) and the
  v4 responses block**, with consistent wording between the two (no body/response conflict).
- **The two errata appear only in a "Kept flagged, NOT silently applied" block** and are not written
  into any spec file by this design. CONFIRMED (flag-only).

## Unverified / Wrong Assumptions

(These are inherited from v3 and are correctly handled by the design's pin-at-implementation
discipline; they are NOT in scope to re-adjudicate this pass and do not affect the verdict. Listed
for completeness.)

- **`pix2tex==0.1.4` exists on PyPI and its weights live at an immutable per-tag release-asset URL
  with filenames `weights.pth`/`image_resizer.pth` at tag `v0.0.1`.** UNVERIFIED (no network). The
  design explicitly treats the tag/filenames/URL as confirm-at-adoption and instructs using the real
  values if they differ — the pin-on-first-fetch story is robust to this being wrong.
- **pix2tex exposes per-token logprobs on the pin.** UNVERIFIED by design (a one-line probe recorded
  in `docs/m2-verification.md`); AC-6's both-ways contract makes either outcome acceptable.
- **The installed `katex@0.16.11` dist exposes a parseable function registry.** UNVERIFIED; the
  verified source-tarball fallback covers the negative case.
- **`torch==2.3.1+cpu` freezes cleanly under PyInstaller.** UNVERIFIED; ONNX fallback recorded as a
  tracked risk (out of scope this pass).

---

## Summary

All four user-settled resolutions are faithfully reflected with the specific mechanics required
(pin-on-first-fetch with real-hash discipline and offline import as a first-class path; both-ways
confidence contract with the vitest "unavailable" assertion and the provisional/M7 sentence; the
KaTeX generator input with primary public-API path and the SHA-recorded source-tarball fallback; the
`ModelProgress` Pydantic model + mirrored TS type + 500 ms polling contract with a terminal stop
condition and per-file/overall bytes). All three NITs are applied, and the two spec errata remain
flagged rather than silently applied. The single remaining NIT is cosmetic and does not block.

Zero HIGH and zero MEDIUM findings → **APPROVED**.
