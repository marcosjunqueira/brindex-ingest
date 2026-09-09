#!/usr/bin/env bash
# Smoke-drives brindex-ingest end-to-end: builds the venv if needed, runs the
# unit tests (fixture-based, no network), then runs the actual CLI against a
# scratch SQLite db, hitting the real BCB endpoints, and prints what landed.
#
# Usage (from repo root):
#   .claude/skills/run-brindex-ingest/driver.sh [--source treasury-direct|ptax|cdi|all]
#
# Defaults to --source cdi: it's the fastest live check (one small JSON GET,
# no ~150KB XLS downloads) that still proves the full path — network fetch,
# parse, upsert, idempotent re-run.
set -euo pipefail
# Resolve repo root relative to this script's own location, not the caller's
# cwd — the driver must work when invoked with an absolute path from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../.."

SOURCE="${1:-cdi}"
if [ "$SOURCE" = "--source" ]; then
  SOURCE="${2:?--source requires a value}"
fi

if [ ! -x .venv/bin/python ]; then
  echo "==> creating venv"
  python3 -m venv .venv
fi
echo "==> installing (editable, with dev deps)"
.venv/bin/pip install -q -e ".[dev]"

echo "==> running unit tests (fixtures only, no network)"
.venv/bin/pytest -q

DB="$(mktemp -u /tmp/brindex-ingest-smoke-XXXXXX.sqlite)"
trap 'rm -f "$DB"' EXIT

echo "==> first run: brindex-ingest --db $DB --source $SOURCE"
.venv/bin/brindex-ingest --db "$DB" --source "$SOURCE"

.venv/bin/python - "$DB" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
series = conn.execute("SELECT COUNT(*) FROM series").fetchone()[0]
points = conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]
print(f"series={series} points={points}")
assert series > 0, "expected at least one series row"
assert points > 0, "expected at least one point row"
for row in conn.execute("SELECT * FROM points ORDER BY date DESC LIMIT 3"):
    print(" sample:", row)
PY

echo "==> second run (idempotency check): same command again"
.venv/bin/brindex-ingest --db "$DB" --source "$SOURCE"

.venv/bin/python - "$DB" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
points = conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]
print(f"points after re-run={points}")
PY

echo "==> OK"
