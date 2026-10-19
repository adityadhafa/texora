"""Make the engine package + scripts importable when running ``pytest benchmarks``.

The proof harness imports ``texora_engine`` (installed via ``pip install -e ".[test]"`` or on the
PYTHONPATH when run from ``engine/``) and the synthetic-PDF generator in ``scripts/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENGINE = _REPO_ROOT / "engine"

for path in (str(_REPO_ROOT), str(_ENGINE)):
    if path not in sys.path:
        sys.path.insert(0, path)
