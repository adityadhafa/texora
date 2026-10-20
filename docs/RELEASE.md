# Releasing Texora

Texora ships as a self-contained Windows installer. The Python OCR engine is frozen into a
single binary with PyInstaller and bundled inside the Tauri app, so the end user installs **one**
thing and never needs Python, Node, or Rust.

## How a release is built (automated, on GitHub's runners)

The release is produced by `.github/workflows/release.yml`, which runs on a `windows-latest`
GitHub-hosted runner — **not on your machine**. Pushing a version tag triggers it to:

1. Freeze the engine sidecar (`scripts/build_engine.py` → PyInstaller).
2. Build the Tauri installers (`pnpm --filter desktop tauri build`) — produces an `.msi` and an
   NSIS `.exe`.
3. Create a GitHub Release for the tag and attach both installers.

## Cutting a release

The app version is `0.1.0` (kept in sync across `apps/desktop/src-tauri/tauri.conf.json`,
`apps/desktop/package.json`, and `apps/desktop/src-tauri/Cargo.toml`). To release it:

```bash
# from the repo root, on the commit you want to ship (main)
git tag v0.1.0
git push origin v0.1.0
```

The `Release` workflow then builds and publishes automatically. Watch it under the repo's
**Actions** tab; when it finishes, the installers appear on the **Releases** page.

You can also trigger it manually from the Actions tab (**Release → Run workflow**) by entering an
existing tag.

> Bump the version in all three files above before tagging a new version (e.g. `0.2.0` → tag
> `v0.2.0`). The tag and the app version should match.

## What the user downloads

On the Releases page the user gets:

- `Texora_0.1.0_x64_en-US.msi` — standard Windows installer, or
- `Texora_0.1.0_x64-setup.exe` — NSIS installer.

Either installs Texora as a normal desktop app. The frozen engine runs locally on loopback with a
per-session token; nothing is sent off the machine.

## First run notes

- On first use of OCR, Texora downloads the model weights once (pix2tex for formulas; ONNX
  layout/text models on demand) and verifies them by checksum. This needs network access the first
  time only; afterward it runs fully offline.
- See `docs/PROGRESS.md` for the current feature status and `docs/LICENSES.md` for the license of
  every bundled dependency and model.

## Building locally (optional, not required for a release)

A local build needs the full toolchain (Python 3.11.9, Node 24.x, Rust stable + MSVC, pnpm
9.15.9). From the repo root:

```bash
python scripts/build_engine.py --python python --triple x86_64-pc-windows-msvc
pnpm install --frozen-lockfile
pnpm --filter desktop tauri build
```

Installers land in `apps/desktop/src-tauri/target/release/bundle/`.
