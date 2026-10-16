"""CLI entrypoint: ``python -m texora_engine --host 127.0.0.1 --port <p> --token <t>``.

The token may also be supplied via the ``TEXORA_ENGINE_TOKEN`` environment variable; the
``--token`` flag takes precedence when both are set. The server always binds loopback.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from texora_engine.app import create_app
from texora_engine.logging_config import get_logger
from texora_engine.settings import Settings


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="texora_engine",
        description="Texora offline OCR engine sidecar (loopback only).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Loopback bind address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="TCP port to bind on the loopback interface.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Bearer token for protected routes (falls back to TEXORA_ENGINE_TOKEN).",
    )
    return parser.parse_args(argv)


def build_settings(argv: list[str] | None = None) -> Settings:
    """Resolve settings from CLI args layered over environment variables."""

    args = _parse_args(argv)
    # Settings() first reads TEXORA_ENGINE_* env vars; explicit CLI flags override them.
    base = Settings()
    token = args.token if args.token is not None else base.token
    return base.model_copy(update={"host": args.host, "port": args.port, "token": token})


def main(argv: list[str] | None = None) -> int:
    """Start the engine with one-shot uvicorn (no reload)."""

    settings = build_settings(argv)
    logger = get_logger("cli")

    if not settings.token:
        logger.error("no bearer token provided; set --token or TEXORA_ENGINE_TOKEN")
        return 2

    app = create_app(settings)
    logger.info("starting engine on %s:%s", settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
