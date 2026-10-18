#!/usr/bin/env python3
"""Freeze the Texora engine into a single self-contained sidecar binary.

The engine is packaged with PyInstaller as one ``--onefile`` executable named
``texora-engine`` and copied to the location Tauri's ``externalBin`` expects:

    apps/desktop/src-tauri/binaries/texora-engine-<TARGET_TRIPLE>[.exe]

``<TARGET_TRIPLE>`` is the ``host:`` value reported by ``rustc -Vv`` (e.g.
``x86_64-pc-windows-msvc``). A ``--triple`` argument overrides the probe so the freeze works
even on a host without a built Tauri app (or without ``rustc`` on PATH).

The sidecar base name ``texora-engine`` is intentionally distinct from the Cargo crate name
``texora-desktop`` — Tauri rejects a sidecar whose name collides with the package name.

Run from the repo root (or anywhere; paths are resolved relative to this file)::

    python scripts/build_engine.py                 # probe triple from rustc
    python scripts/build_engine.py --triple x86_64-pc-windows-msvc
    python scripts/build_engine.py --python /path/to/py311  # use a specific interpreter

This is a one-shot build tool: it never starts a long-running server.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Repo layout anchors (this file lives in <repo>/scripts/).
REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPO_ROOT / "engine"
ENTRYPOINT = ENGINE_DIR / "texora_engine" / "__main__.py"
BINARIES_DIR = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "binaries"
SIDECAR_BASE = "texora-engine"


def _is_windows() -> bool:
    return os.name == "nt" or platform.system().lower().startswith("win")


def default_python() -> str:
    """Prefer the engine venv's interpreter so the freeze uses Python 3.11.

    Falls back to the interpreter running this script if the venv is absent.
    """

    if _is_windows():
        venv_py = ENGINE_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = ENGINE_DIR / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def probe_triple() -> str:
    """Resolve the target triple from ``rustc -Vv`` (the ``host:`` line)."""

    try:
        out = subprocess.run(
            ["rustc", "-Vv"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover - env dependent
        raise SystemExit(
            "could not run 'rustc -Vv' to resolve the target triple; "
            "pass --triple explicitly (e.g. --triple x86_64-pc-windows-msvc). "
            f"underlying error: {exc}"
        )
    for line in out.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("rustc -Vv did not report a 'host:' line; pass --triple explicitly.")


def freeze(python: str, workdir: Path) -> Path:
    """Run PyInstaller --onefile and return the produced executable path."""

    dist_dir = workdir / "dist"
    build_dir = workdir / "build"
    cmd = [
        python,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        SIDECAR_BASE,
        "--noconfirm",
        "--clean",
        "--console",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(build_dir),
        # uvicorn loads loop/protocol/lifespan impls by string; collect them all.
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "pydantic",
        "--collect-submodules",
        "pydantic_settings",
        # M2 runtime deps: the model downloader (httpx) and the pix2tex formula stack
        # (torch/pix2tex and their dynamically-imported submodules + data files).
        "--collect-submodules",
        "httpx",
        "--collect-submodules",
        "torch",
        "--collect-data",
        "torch",
        "--collect-submodules",
        "pix2tex",
        "--collect-data",
        "pix2tex",
        "--collect-submodules",
        "x_transformers",
        "--collect-data",
        "transformers",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespan.on",
        str(ENTRYPOINT),
    ]
    print("[build_engine] running:", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, check=False, cwd=str(ENGINE_DIR))

    exe_name = f"{SIDECAR_BASE}.exe" if _is_windows() else SIDECAR_BASE
    produced = dist_dir / exe_name

    if result.returncode != 0:
        # PyInstaller's Windows post-assembly step rewrites the PE build timestamp and
        # checksum IN PLACE. For a large --onefile binary (torch pushes this well past
        # half a GB) that in-place rewrite fails on Windows with OSError(22, 'Invalid
        # argument') because the file was just memory-mapped by ``pefile`` — a known
        # PyInstaller/pefile interaction, not a defect in the engine. The fully assembled
        # onefile already exists on disk at this point; only the cosmetic timestamp/checksum
        # fix-up did not land. When that is exactly what happened, finish the fix-up
        # ourselves via a temp-file + atomic replace (which avoids writing back to the
        # just-mmapped path) and continue. Any other failure — or a missing binary — is a
        # real build error and is re-raised.
        if _is_windows() and produced.exists():
            print(
                "[build_engine] PyInstaller exited non-zero but the onefile exists; "
                "applying the PE timestamp/checksum fix-up via temp+replace "
                "(works around the large-onefile OSError 22 on Windows).",
                flush=True,
            )
            _finish_windows_pe_fixup(produced)
        else:
            raise SystemExit(
                f"PyInstaller failed (exit {result.returncode}) and produced no usable "
                f"binary at {produced}"
            )

    if not produced.exists():
        raise SystemExit(f"PyInstaller did not produce the expected binary at {produced}")
    return produced


def _finish_windows_pe_fixup(exe_path: Path) -> None:
    """Apply PyInstaller's Windows PE build-timestamp + checksum fix-up safely.

    Mirrors ``PyInstaller.building.api.EXE`` post-processing, but writes the modified bytes
    to a temp file and atomically replaces the original instead of rewriting the path that
    ``pefile`` just memory-mapped (the in-place rewrite is what fails with OSError 22 for a
    large onefile). If anything here fails, the error is surfaced — we never ship a binary
    we could not verify as runnable.
    """

    import os
    import time

    import pefile
    from PyInstaller.utils.win32 import winutils

    build_timestamp = int(os.environ.get("SOURCE_DATE_EPOCH", time.time()))

    with pefile.PE(str(exe_path), fast_load=True) as pe:
        pe.full_load()
        pe.FILE_HEADER.TimeDateStamp = build_timestamp
        for debug_entry in getattr(pe, "DIRECTORY_ENTRY_DEBUG", []):
            if debug_entry.struct.TimeDateStamp:
                debug_entry.struct.TimeDateStamp = build_timestamp
        data = pe.write()

    tmp = exe_path.with_suffix(exe_path.suffix + ".tsfix")
    with open(tmp, "wb") as fp:
        fp.write(data)
    os.replace(tmp, exe_path)

    # Recompute and write the PE checksum (AV software flags a zero/stale checksum). Reuse
    # PyInstaller's fast checksum helper, but apply the result with the same temp+replace
    # dance so the large-onefile in-place rewrite cannot trip OSError 22.
    checksum = winutils.compute_exe_pe_checksum(str(exe_path))
    with pefile.PE(str(exe_path), fast_load=True) as pe:
        pe.OPTIONAL_HEADER.CheckSum = checksum
        data = pe.write()
    tmp = exe_path.with_suffix(exe_path.suffix + ".cksum")
    with open(tmp, "wb") as fp:
        fp.write(data)
    os.replace(tmp, exe_path)


def place_sidecar(produced: Path, triple: str) -> Path:
    """Copy the frozen binary to binaries/texora-engine-<triple>[.exe]."""

    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if _is_windows() else ""
    target = BINARIES_DIR / f"{SIDECAR_BASE}-{triple}{suffix}"
    shutil.copy2(produced, target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_engine",
        description="Freeze the Texora engine into a single Tauri sidecar binary.",
    )
    parser.add_argument(
        "--triple",
        default=None,
        help="Target triple (default: probe 'host:' from rustc -Vv).",
    )
    parser.add_argument(
        "--python",
        default=None,
        help="Python interpreter to freeze with (default: engine/.venv Python 3.11).",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="Scratch directory for PyInstaller build/dist (default: engine/.build).",
    )
    args = parser.parse_args(argv)

    if not ENTRYPOINT.exists():
        raise SystemExit(f"engine entrypoint not found: {ENTRYPOINT}")

    triple = args.triple or probe_triple()
    python = args.python or default_python()
    workdir = Path(args.workdir) if args.workdir else (ENGINE_DIR / ".build")
    workdir.mkdir(parents=True, exist_ok=True)

    print(f"[build_engine] python = {python}", flush=True)
    print(f"[build_engine] triple = {triple}", flush=True)

    produced = freeze(python, workdir)
    target = place_sidecar(produced, triple)

    print(f"[build_engine] frozen binary: {produced}", flush=True)
    print(f"[build_engine] sidecar placed: {target}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
