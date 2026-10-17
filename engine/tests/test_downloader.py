"""Downloader checksum accept/reject tests against a local HTTP server.

These exercise download/verify plumbing — NOT OCR — so a local fake server is allowed.
"""

from __future__ import annotations

import hashlib
import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from texora_engine.models import ChecksumMismatch, ModelFile, ModelSpec, download_model


class _Handler(http.server.BaseHTTPRequestHandler):
    directory: str = ""

    def do_GET(self) -> None:  # noqa: N802 (stdlib signature)
        path = Path(self.directory) / self.path.lstrip("/")
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:  # silence test server noise
        return


@pytest.fixture()
def http_server(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    serve_dir = tmp_path / "serve"
    serve_dir.mkdir()
    _Handler.directory = str(serve_dir)
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    try:
        yield f"http://{host}:{port}", serve_dir
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _spec(base_url: str, target: Path, name: str, data: bytes, sha: str) -> ModelSpec:
    return ModelSpec(
        id="test-model",
        version="v0",
        license="MIT",
        target_dir=target,
        files=[ModelFile(name=name, url=f"{base_url}/{name}", sha256=sha, size=len(data))],
    )


def test_download_verifies_and_installs(http_server: tuple[str, Path], tmp_path: Path) -> None:
    base_url, serve_dir = http_server
    data = b"pretend-model-weights-bytes" * 100
    (serve_dir / "weights.bin").write_bytes(data)
    good_sha = hashlib.sha256(data).hexdigest()

    target = tmp_path / "models" / "test-model"
    spec = _spec(base_url, target, "weights.bin", data, good_sha)

    events = []
    download_model(spec, on_progress=events.append)

    installed = target / "weights.bin"
    assert installed.exists()
    assert installed.read_bytes() == data
    # No leftover .part temp.
    assert not list((target / ".incoming").glob("*.part"))
    # Terminal progress event is READY.
    assert events[-1].state.value == "ready"


def test_bad_hash_is_rejected(http_server: tuple[str, Path], tmp_path: Path) -> None:
    base_url, serve_dir = http_server
    data = b"corrupt-bytes" * 100
    (serve_dir / "weights.bin").write_bytes(data)
    wrong_sha = "0" * 64  # deliberately wrong

    target = tmp_path / "models" / "test-model"
    spec = _spec(base_url, target, "weights.bin", data, wrong_sha)

    with pytest.raises(ChecksumMismatch):
        download_model(spec)

    # The .part is deleted and the file is NOT promoted.
    assert not (target / "weights.bin").exists()
    assert not list((target / ".incoming").glob("*.part"))
