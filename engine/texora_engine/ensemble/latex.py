"""LaTeX validation + normalization (single-engine subset of the M5 ensemble).

``validate_and_normalize(latex)`` parses with pylatexenc, structurally checks balanced
braces / matched ``\\left``\\``\\right`` / matched ``\\begin{env}``\\``\\end{env}``, checks
every command/environment against the generated KaTeX-supported allow-list, then normalizes
for compilability. It returns the normalized string plus the shared
:class:`RecognitionStatus`:

- parse/structure failure  -> ``failed``
- command/env outside the allow-list -> ``needs_review``
- otherwise -> ``ok``

The engine asserts "structurally valid + macros within the KaTeX-supported set" — it never
claims a KaTeX render it did not perform. The authoritative KaTeX render lives in the UI /
vitest (design §B.6). A too-strict allow-list only downgrades to ``needs_review``; it never
fabricates.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pylatexenc.latexwalker import LatexWalker, LatexWalkerError

from texora_engine.recognizers.base import RecognitionStatus

_ALLOWLIST_PATH = Path(__file__).resolve().parent / "katex_allowlist.json"


@lru_cache(maxsize=1)
def _allowlist() -> tuple[frozenset[str], frozenset[str]]:
    data = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return frozenset(data["commands"]), frozenset(data["environments"])


def _structure_ok(latex: str) -> bool:
    """Balanced braces + matched \\left/\\right + matched \\begin/\\end."""

    # Braces (ignoring escaped \{ \}).
    depth = 0
    i = 0
    n = len(latex)
    while i < n:
        ch = latex[i]
        if ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    if depth != 0:
        return False

    # \left ... \right balance.
    lefts = len(re.findall(r"\\left(?![a-zA-Z])", latex))
    rights = len(re.findall(r"\\right(?![a-zA-Z])", latex))
    if lefts != rights:
        return False

    # \begin{env} ... \end{env} balance (counts + name matching via a stack).
    stack: list[str] = []
    for kind, name in re.findall(r"\\(begin|end)\{([^}]*)\}", latex):
        if kind == "begin":
            stack.append(name)
        else:
            if not stack or stack.pop() != name:
                return False
    return not stack


def _commands_in(latex: str) -> set[str]:
    """All backslash-commands used (``\\frac``, ``\\alpha``, …), excluding begin/end."""

    cmds = set()
    for m in re.findall(r"\\([a-zA-Z]+|.)", latex):
        token = "\\" + m
        cmds.add(token)
    cmds.discard("\\begin")
    cmds.discard("\\end")
    return cmds


def _environments_in(latex: str) -> set[str]:
    return {name for _, name in re.findall(r"\\(begin|end)\{([^}]*)\}", latex)}


# Structural TeX tokens that are not registered katex "commands" but are always valid.
_ALWAYS_OK_COMMANDS = frozenset(
    {
        "\\left",
        "\\right",
        "\\{",
        "\\}",
        "\\|",
        "\\,",
        "\\;",
        "\\:",
        "\\!",
        "\\ ",
        "\\\\",
        "\\%",
        "\\&",
        "\\#",
        "\\_",
        "\\$",
    }
)


def _normalize(latex: str) -> str:
    """Rule-based normalization that preserves mathematical meaning.

    Each rule keeps the output valid (asserted by golden tests): canonical \\frac, collapse
    redundant whitespace, and a single space normalization. Intentionally conservative.
    """

    out = latex.strip()
    # \dfrac/\tfrac -> \frac (display/text fraction variants canonicalized).
    out = re.sub(r"\\dfrac(?![a-zA-Z])", r"\\frac", out)
    out = re.sub(r"\\tfrac(?![a-zA-Z])", r"\\frac", out)
    # Collapse runs of plain spaces/tabs (not touching escaped spaces "\ ").
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def validate_and_normalize(latex: str) -> tuple[str, RecognitionStatus]:
    """Validate + normalize ``latex``; return ``(normalized, status)``."""

    raw = (latex or "").strip()
    if not raw:
        return "", RecognitionStatus.FAILED

    # Parse — a hard parse error is `failed`.
    try:
        LatexWalker(raw).get_latex_nodes()
    except LatexWalkerError:
        return raw, RecognitionStatus.FAILED

    if not _structure_ok(raw):
        return raw, RecognitionStatus.FAILED

    commands, environments = _allowlist()
    used_cmds = _commands_in(raw)
    unknown_cmds = {
        c for c in used_cmds if c not in commands and c not in _ALWAYS_OK_COMMANDS and len(c) > 1
    }
    used_envs = _environments_in(raw)
    unknown_envs = used_envs - environments

    status = RecognitionStatus.OK
    if unknown_cmds or unknown_envs:
        status = RecognitionStatus.NEEDS_REVIEW

    normalized = _normalize(raw)
    # Normalization must never break a previously-valid structure.
    if status == RecognitionStatus.OK and not _structure_ok(normalized):
        return raw, RecognitionStatus.NEEDS_REVIEW
    return normalized, status
