"""SQLite schema and connection helper shared by every source's ingestion.

Schema mirrors the design in `.specs/New/SPEC_INGESTAO.md` and is read, unmodified,
by the sibling `brindex-api` repo — the two must stay in sync by hand until this
schema is stable enough to version formally.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS series (
  codigo        TEXT PRIMARY KEY,
  dominio       TEXT NOT NULL,
  nome          TEXT NOT NULL,
  metadados     TEXT NOT NULL,
  criado_em     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pontos (
  serie_codigo  TEXT NOT NULL REFERENCES series(codigo),
  data          TEXT NOT NULL,
  valor         TEXT NOT NULL,
  valores_extra TEXT,
  fonte_atualizado_em TEXT NOT NULL,
  PRIMARY KEY (serie_codigo, data)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (and, on first run, create) the BRIndex SQLite database at `db_path`."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn
