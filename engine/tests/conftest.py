"""Shared pytest fixtures for engine tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from texora_engine.app import create_app
from texora_engine.settings import Settings

TEST_TOKEN = "test-token-abc123"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Settings with a known token and an isolated log directory."""

    return Settings(host="127.0.0.1", port=8756, token=TEST_TOKEN, log_dir=tmp_path / "logs")


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    """A TestClient wrapping a freshly built app."""

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
