#!/usr/bin/env python3
"""One-shot smoke test for the frozen Texora engine sidecar.

Launches the frozen binary on a free loopback port with a session token, polls
``/healthz`` until it returns 200 (or times out), prints the result, then ALWAYS
terminates the child process. This never leaves a server running.

Usage:
    python scripts/smoke_sidecar.py [--binary <path>] [--timeout <seconds>]
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BINARY = (
    REPO_ROOT
    / "apps"
    / "desktop"
    / "src-tauri"
    / "binaries"
    / "texora-engine-x86_64-pc-windows-msvc.exe"
)


def _terminate_tree(proc: subprocess.Popen) -> None:
    """Terminate the child and every descendant; never leave the sidecar running.

    PyInstaller onefile binaries re-exec into a child process, so terminating the parent
    handle alone can orphan the actual server. On Windows we use ``taskkill /T`` to reap the
    whole tree; elsewhere we fall back to terminate/kill on the process handle.
    """

    if proc.poll() is None:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smoke_sidecar")
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args(argv)

    binary = Path(args.binary)
    if not binary.exists():
        print(f"SMOKE FAIL: binary not found at {binary}")
        return 1

    port = free_port()
    token = "smoke-token-abc123"
    url = f"http://127.0.0.1:{port}/healthz"
    print(f"SMOKE: launching {binary.name} on 127.0.0.1:{port}")

    # On Windows a onefile PyInstaller binary spawns a child; create a new process group so
    # teardown via taskkill /T can reap every descendant and never leave a server running.
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [str(binary), "--host", "127.0.0.1", "--port", str(port), "--token", token],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
    )

    status = None
    body = ""
    deadline = time.time() + args.timeout
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                print(f"SMOKE FAIL: process exited early with code {proc.returncode}")
                break
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    status = resp.status
                    body = resp.read().decode("utf-8", "replace")
                    break
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
    finally:
        _terminate_tree(proc)

    print(f"SMOKE: /healthz status = {status}")
    print(f"SMOKE: /healthz body   = {body}")
    if status == 200:
        print("SMOKE PASS: frozen sidecar served /healthz with 200.")
        return 0
    print("SMOKE FAIL: did not get 200 from /healthz.")
    # Surface child output for debugging on failure.
    if proc.stdout is not None:
        try:
            remaining = proc.stdout.read()
            if remaining:
                print("---- child output ----")
                print(remaining)
        except Exception:  # pragma: no cover
            pass
    return 1


if __name__ == "__main__":
    sys.exit(main())
