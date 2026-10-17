"""The generated allow-list must track the pinned katex version (cannot drift)."""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALLOWLIST = _REPO_ROOT / "engine" / "texora_engine" / "ensemble" / "katex_allowlist.json"
_PKG_JSON = _REPO_ROOT / "apps" / "desktop" / "package.json"


def test_allowlist_version_matches_katex_pin() -> None:
    allow = json.loads(_ALLOWLIST.read_text(encoding="utf-8"))
    pkg = json.loads(_PKG_JSON.read_text(encoding="utf-8"))
    assert allow["_generated_from"]["katex_version"] == pkg["dependencies"]["katex"]


def test_allowlist_has_core_commands() -> None:
    allow = json.loads(_ALLOWLIST.read_text(encoding="utf-8"))
    commands = set(allow["commands"])
    for c in ["\\frac", "\\sqrt", "\\sum", "\\alpha", "\\mathrm", "\\operatorname"]:
        assert c in commands
    assert "matrix" in set(allow["environments"])
