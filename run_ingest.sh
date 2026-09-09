#!/usr/bin/env bash
# Runs brindex-ingest against the project venv. Meant to be invoked daily by cron/systemd
# timer (see .specs/New/SPEC_INGESTION.md §5).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

VENV_DIR="${VENV_DIR:-.venv}"

if [ ! -x "$VENV_DIR/bin/brindex-ingest" ]; then
    echo "creating venv and installing brindex-ingest into $VENV_DIR" >&2
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -e .
fi

exec "$VENV_DIR/bin/brindex-ingest" --db "${BRINDEX_DB_PATH:-brindex.sqlite}" --source "${BRINDEX_SOURCE:-all}" "$@"
