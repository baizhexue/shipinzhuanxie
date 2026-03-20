#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  exec "$REPO_ROOT/.venv/bin/python" "$SCRIPT_DIR/one_click_deploy.py" --mode auto --host 127.0.0.1 --port 8000 "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$SCRIPT_DIR/one_click_deploy.py" --mode auto --host 127.0.0.1 --port 8000 "$@"
fi

if command -v python >/dev/null 2>&1; then
  exec python "$SCRIPT_DIR/one_click_deploy.py" --mode auto --host 127.0.0.1 --port 8000 "$@"
fi

echo "Python 3.9+ was not found. Install Python first, then rerun this script." >&2
exit 1
