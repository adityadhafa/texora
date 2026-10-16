#!/usr/bin/env bash
# Freeze the Texora engine sidecar (POSIX / bash wrapper around scripts/build_engine.py).
#
# Usage:
#   scripts/build-engine.sh [--triple <triple>] [--python <interpreter>]
#
# Prefers the engine venv interpreter (engine/.venv) so the freeze targets Python 3.11.
# All arguments are forwarded verbatim to the cross-platform driver.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Pick an interpreter to *run the driver with*; the driver itself defaults to the engine venv
# for the actual freeze. On Windows the venv layout is Scripts/python.exe.
if [ -x "${REPO_ROOT}/engine/.venv/bin/python" ]; then
  PY="${REPO_ROOT}/engine/.venv/bin/python"
elif [ -x "${REPO_ROOT}/engine/.venv/Scripts/python.exe" ]; then
  PY="${REPO_ROOT}/engine/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi

exec "${PY}" "${SCRIPT_DIR}/build_engine.py" "$@"
