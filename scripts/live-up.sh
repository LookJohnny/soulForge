#!/usr/bin/env bash
# ./scripts/live-up.sh --check: validate root .env without starting anything.
# ./scripts/live-up.sh status: read-only local health checks.
# ./scripts/live-up.sh: foreground; Ctrl-C stops only owned child processes.
set -euo pipefail
SF_PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SF_PROJECT_ROOT"
if [[ ! -x "$SF_PROJECT_ROOT/.venv/bin/python" ]]; then
  echo 'Missing .venv/bin/python. Run uv sync --all-packages first.' >&2
  exit 2
fi
exec "$SF_PROJECT_ROOT/.venv/bin/python" "$SF_PROJECT_ROOT/scripts/live_stack.py" "$@"
