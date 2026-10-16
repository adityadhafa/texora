# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for freezing the Texora engine into a single self-contained binary.

This spec is optional: ``scripts/build_engine.py`` drives PyInstaller directly with the
equivalent flags. It is kept here so the freeze can also be run with
``pyinstaller engine/texora-engine.spec`` and so the uvicorn/pydantic hidden imports are
declared in one reviewable place.

The output base name is ``texora-engine`` (deliberately distinct from the Cargo crate
``texora-desktop`` so Tauri does not reject a sidecar/package name collision).
"""

from PyInstaller.utils.hooks import collect_submodules

# uvicorn loads its protocol/loop/lifespan implementations lazily by string, so PyInstaller's
# static analysis misses them unless we collect the whole package. pydantic v2 keeps most of its
# runtime in the compiled pydantic_core, but collecting pydantic submodules is cheap insurance.
hidden_imports = (
    collect_submodules("uvicorn")
    + collect_submodules("pydantic")
    + collect_submodules("pydantic_settings")
    + [
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ]
)


a = Analysis(
    ["texora_engine/__main__.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="texora-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
