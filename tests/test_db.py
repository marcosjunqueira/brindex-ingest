from pathlib import Path

from brindex_ingest.db import connect


def test_connect_creates_schema(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.sqlite")
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"series", "pontos"} <= tables
