from pathlib import Path

from brindex_ingest.db import PointRow, connect, upsert_points, upsert_series


def test_connect_creates_schema(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.sqlite")
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"series", "points"} <= tables


def test_upsert_points_accepts_null_value(tmp_path: Path) -> None:
    """Regression test: a missing/malformed source cell must become SQL NULL (SPEC_INGESTION.md
    §6/§7), so `points.value` must not be NOT NULL. It briefly was, in both the schema and
    db.py — `upsert_points` with a None value raised `sqlite3.IntegrityError` instead of storing
    NULL, and no test caught it because the money-boundary tests only exercised parsing in
    isolation, never a full round trip through the database."""
    conn = connect(tmp_path / "test.sqlite")
    upsert_series(conn, "TEST:1", "test", "name", {}, "2026-01-01T00:00:00Z")
    upsert_points(
        conn,
        [PointRow("TEST:1", "2026-01-01", None, None, "2026-01-01T00:00:00Z")],
    )
    conn.commit()
    value = conn.execute(
        "SELECT value FROM points WHERE series_code = 'TEST:1' AND date = '2026-01-01'"
    ).fetchone()[0]
    assert value is None
