#!/usr/bin/env bash
# Independent Python 3.12 environment; never sync/remove the live stack's packages.
set -euo pipefail
SF_MEDIA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SF_MEDIA_DIR="$SF_MEDIA_ROOT/packages/media-body"
cd "$SF_MEDIA_ROOT"
if [[ "${1:-}" == "--install" ]]; then
  UV_PROJECT_ENVIRONMENT="$SF_MEDIA_DIR/.venv" uv sync --project "$SF_MEDIA_DIR" --frozen --python 3.12 --extra test
  exit 0
fi
if [[ ! -x "$SF_MEDIA_DIR/.venv/bin/python" ]]; then
  echo 'Run scripts/selfhost-up.sh --install first.' >&2
  exit 2
fi
# Explicit source path also handles Python ignoring hidden editable .pth files on macOS.
export PYTHONPATH="$SF_MEDIA_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ "${1:-}" == "--status" ]]; then
  exec "$SF_MEDIA_DIR/.venv/bin/python" -m media_body.probe --health
fi
exec "$SF_MEDIA_DIR/.venv/bin/python" -m media_body.server
