#!/usr/bin/env sh
set -eu

MIGRATION_DATABASE_URL="${ASP_DATABASE_URL:-}"
unset ASP_DATABASE_URL
export PYTHON_BIN="${PYTHON_BIN:-python3.11}"

"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
PYTHONPATH=src "$PYTHON_BIN" -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/a-share-platform-pycache "$PYTHON_BIN" -m compileall -q src
"$PYTHON_BIN" -m ruff check src tests
"$PYTHON_BIN" -m mypy src

if [ -n "$MIGRATION_DATABASE_URL" ]; then
  ASP_DATABASE_URL="$MIGRATION_DATABASE_URL" \
    PYTHONPATH=src "$PYTHON_BIN" -m a_share_platform.adapters.postgres.cli
fi

if [ -f frontend/package-lock.json ]; then
  npm --prefix frontend ci
  npm --prefix frontend run generate:api
  npm --prefix frontend run lint
  npm --prefix frontend test -- --run
  npm --prefix frontend run build
fi
