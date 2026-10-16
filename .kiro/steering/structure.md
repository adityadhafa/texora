# Structure — Texora

Monorepo layout. Keep modules cohesive and the UI free of ML logic.

```
texora/
├─ apps/desktop/              # Tauri + React UI
│  ├─ src/                    # React/TS: screens, components, state, i18n, typed engine client
│  ├─ src-tauri/             # Rust: supervisor, hotkey, vault, externalBin wiring
│  │  └─ binaries/           # frozen engine sidecar (<name>-$TARGET_TRIPLE)
│  └─ e2e/                    # Tauri driver / Playwright
├─ engine/                    # Python sidecar
│  ├─ texora_engine/
│  │  ├─ api/                 # FastAPI routes + websockets (progress)
│  │  ├─ ingest/              # pdf/image loading, preprocessing
│  │  ├─ layout/              # layout detection + reading order
│  │  ├─ recognizers/         # text, formula, table, handwriting adapters (base.py Protocols)
│  │  ├─ ensemble/            # voting, verification, LaTeX validation/normalization
│  │  ├─ export/              # tex, md, docx(OMML), html, mathml, json, pdf
│  │  ├─ jobs/                # queue, checkpointing, scheduler
│  │  ├─ models/              # registry, downloader, checksums
│  │  └─ db/                  # SQLite schema, migrations, FTS5
│  └─ tests/                  # pytest: unit, integration, golden-file
├─ benchmarks/                # harness, dataset loaders, metrics
├─ docs/                      # BENCHMARKS.md, LICENSES.md, README assets, architecture
├─ scripts/                   # build, package, model prefetch, synthetic-pdf generator
├─ pipeline.yaml              # default pipeline config (engine ids per stage)
└─ .kiro/                     # specs, steering, hooks
```

## Conventions
- One engine adapter per file under the matching `recognizers/` or `layout/` folder; register it in
  the pipeline factory. Never hard-wire an engine into the API or UI.
- Config via `pipeline.yaml` + Pydantic settings; no magic constants scattered in code.
- SQLite access goes through `db/`; no raw SQL in route handlers.
- Exports go through `export/` with golden-file fixtures under `engine/tests/`.
- Shared TS types for the engine API live in one typed client module in `apps/desktop/src`.
- New dependency → add a row to `docs/LICENSES.md` in the same change.
