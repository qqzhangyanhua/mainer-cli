#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PY="${SCRIPT_DIR}/install.py"

if [[ ! -f "${INSTALL_PY}" ]]; then
  echo "Error: install.py not found at ${INSTALL_PY}" >&2
  exit 1
fi

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  echo ""
}

PYTHON_BIN="$(find_python)"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "Error: Python is required (>=3.9)." >&2
  exit 1
fi

"${PYTHON_BIN}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "Error: ${PYTHON_BIN} version must be >= 3.9." >&2
  exit 1
}

exec "${PYTHON_BIN}" "${INSTALL_PY}" "$@"
