"""SQLite schema and connection helper shared by every source's ingestion.

Schema mirrors the design in `.specs/New/SPEC_INGESTION.md` and is read, unmodified,
by the sibling `brindex-api` repo — the two must stay in sync by hand until this
schema is stable enough to version formally.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, NamedTuple

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS series (
  code          TEXT PRIMARY KEY,
  domain        TEXT NOT NULL,
  name          TEXT NOT NULL,
  metadata      TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS points (
  series_code   TEXT NOT NULL REFERENCES series(code),
  date          TEXT NOT NULL,
  value         TEXT,
  extra_values  TEXT,
  source_updated_at TEXT NOT NULL,
  PRIMARY KEY (series_code, date)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (and, on first run, create) the BRIndex SQLite database at `db_path`."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    _check_schema(conn, db_path)
    return conn


def _check_schema(conn: sqlite3.Connection, db_path: Path) -> None:
    """`CREATE TABLE IF NOT EXISTS` can't retroactively relax `NOT NULL` on a database
    created before `points.value` was made nullable (SPEC_INGESTION.md's money-boundary
    fix) — fail loudly here instead of surfacing a generic IntegrityError deep inside a
    later ingestion run."""
    for row in conn.execute("PRAGMA table_info(points)"):
        name, notnull = row[1], row[3]
        if name == "value" and notnull:
            raise RuntimeError(
                f"{db_path}: points.value is NOT NULL, which predates this project's "
                "money-boundary fix (a missing/malformed source value must be storable "
                "as NULL). Recreate the database file — there is no migration tool yet."
            )


class PointRow(NamedTuple):
    series_code: str
    date: str
    value: str | None
    extra_values: str | None
    source_updated_at: str


def upsert_series(
    conn: sqlite3.Connection,
    code: str,
    domain: str,
    name: str,
    metadata: dict,
    created_at: str,
) -> None:
    """Insert or update a `series` row. `created_at` is preserved across updates — only
    `domain`/`name`/`metadata` are refreshed, since it reflects when we first saw this series."""
    conn.execute(
        """
        INSERT INTO series (code, domain, name, metadata, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            domain = excluded.domain,
            name = excluded.name,
            metadata = excluded.metadata
        """,
        (code, domain, name, json.dumps(metadata), created_at),
    )


def upsert_points(conn: sqlite3.Connection, points: Iterable[PointRow]) -> None:
    """Insert or update `points` rows, overwriting `value`/`extra_values`/`source_updated_at`
    on conflict — never delete-then-insert (see `.specs/New/SPEC_INGESTION.md` §4)."""
    conn.executemany(
        """
        INSERT INTO points (series_code, date, value, extra_values, source_updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(series_code, date) DO UPDATE SET
            value = excluded.value,
            extra_values = excluded.extra_values,
            source_updated_at = excluded.source_updated_at
        """,
        points,
    )
