"""SQLite schema and connection helper shared by every source's ingestion.

Schema mirrors the design in `.specs/New/SPEC_INGESTION.md` and is read, unmodified,
by the sibling `brindex-api` repo — the two must stay in sync by hand until this
schema is stable enough to version formally.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

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
  value         TEXT NOT NULL,
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
    return conn
