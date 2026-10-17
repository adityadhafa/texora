"""Generate the KaTeX supported-command/environment allow-list from the pinned katex.

The allow-list is GENERATED (never hand-typed) so it cannot silently drift from the pinned
``katex`` version. Primary input = the installed package's shipped ESM bundle
``dist/katex.mjs`` (the public function registry: ``defineFunction({names: [...]})``,
``defineMacro("\\name", ...)``, ``defineEnvironment({names: [...]})``). The published npm
dist ships this parseable registry, so no source tarball fallback was needed for
katex@0.16.11 (confirmed at implementation time — see docs/m2-verification.md).

Output: ``engine/texora_engine/ensemble/katex_allowlist.json`` with a header recording the
katex version it was generated from. A pytest asserts that recorded version equals the
``katex`` pin in ``apps/desktop/package.json``, so bumping katex without regenerating fails
CI rather than drifting.

Usage (from the repo root):
    python scripts/gen_katex_allowlist.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PKG_JSON = _REPO_ROOT / "apps" / "desktop" / "package.json"
_OUT = _REPO_ROOT / "engine" / "texora_engine" / "ensemble" / "katex_allowlist.json"

# Candidate locations of the installed katex dist (pnpm layout + plain node_modules).
_KATEX_CANDIDATES = [
    _REPO_ROOT / "apps" / "desktop" / "node_modules" / "katex",
]


def _pinned_katex_version() -> str:
    data = json.loads(_PKG_JSON.read_text(encoding="utf-8"))
    return str(data["dependencies"]["katex"])


def _find_katex_mjs(version: str) -> Path:
    # Direct candidates first.
    for base in _KATEX_CANDIDATES:
        mjs = base / "dist" / "katex.mjs"
        if mjs.exists():
            return mjs
    # pnpm virtual store: node_modules/.pnpm/katex@<version>/node_modules/katex/dist/katex.mjs
    pnpm_store = _REPO_ROOT / "node_modules" / ".pnpm" / f"katex@{version}" / "node_modules" / "katex"
    mjs = pnpm_store / "dist" / "katex.mjs"
    if mjs.exists():
        return mjs
    raise FileNotFoundError(
        "could not locate katex dist/katex.mjs; run `pnpm install` first "
        f"(looked under apps/desktop/node_modules and {pnpm_store})"
    )


def _parse_names_arrays(text: str) -> set[str]:
    """Collect every token inside `names: [ ... ]` arrays (functions + environments)."""

    names: set[str] = set()
    for arr in re.findall(r"names\s*:\s*\[([^\]]*)\]", text):
        for m in re.findall(r"""['"]((?:\\\\|[^'"])+)['"]""", arr):
            token = m.replace("\\\\", "\\")
            if token:
                names.add(token)
    return names


def _parse_define_macros(text: str) -> set[str]:
    """Collect every macro name registered via `defineMacro("\\name", ...)`."""

    names: set[str] = set()
    for m in re.findall(r"""defineMacro\(\s*['"]((?:\\\\|[^'"])+)['"]""", text):
        names.add(m.replace("\\\\", "\\"))
    return names


def _parse_define_symbols(text: str) -> set[str]:
    """Collect LaTeX command names registered via `defineSymbol(..., "\\name")`.

    defineSymbol's last string arg is the LaTeX name; it may be a single literal character
    (e.g. a letter/number) rather than a backslash command — we keep only backslash
    commands for the allow-list (literals are always allowed as ordinary characters).
    """

    names: set[str] = set()
    pattern = (
        r"""defineSymbol\(\s*\w+\s*,\s*\w+\s*,\s*\w+\s*,\s*"""
        r"""['"](?:\\\\|[^'"])*['"]\s*,\s*['"]((?:\\\\|[^'"])+)['"]"""
    )
    for m in re.findall(pattern, text):
        token = m.replace("\\\\", "\\")
        if token.startswith("\\"):
            names.add(token)
    return names


def generate() -> dict[str, object]:
    version = _pinned_katex_version()
    mjs = _find_katex_mjs(version)
    text = mjs.read_text(encoding="utf-8")

    names_tokens = _parse_names_arrays(text)
    all_tokens = names_tokens | _parse_define_macros(text) | _parse_define_symbols(text)

    # Backslash-led commands are the allow-listed macros.
    command_set = sorted(c for c in all_tokens if c.startswith("\\"))
    # Environment names come only from the `names:` arrays (defineEnvironment); keep bare
    # identifier-like tokens (letters, optional trailing * / digits), dropping punctuation
    # noise such as "$" or ", " that appears in unrelated `names:` arrays.
    env_re = re.compile(r"^[A-Za-z][A-Za-z0-9]*\*?$")
    environment_set = sorted(c for c in names_tokens if env_re.match(c))

    return {
        "_generated_from": {
            "tool": "scripts/gen_katex_allowlist.py",
            "katex_version": version,
            "source": "dist/katex.mjs (public function registry)",
        },
        "commands": command_set,
        "environments": environment_set,
    }


def main() -> None:
    data = generate()
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    counts = (len(data["commands"]), len(data["environments"]))  # type: ignore[arg-type]
    print(f"wrote {_OUT} (commands={counts[0]}, environments={counts[1]})")


if __name__ == "__main__":
    main()
