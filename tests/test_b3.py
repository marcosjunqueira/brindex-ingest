import io
import zipfile
from pathlib import Path

from brindex_ingest.sources.b3 import canonical_code, parse_lines, parse_zip

# Synthetic records built from B3's published COTAHIST layout (SPEC_INGESTION.md §2.2),
# not a real download: the real annual file is ~100 MB and B3's host is unreachable from
# the environment this fixture was written in.
FIXTURE = Path(__file__).parent / "fixtures" / "cotahist_sample.txt"


def _points():
    with FIXTURE.open(encoding="latin-1") as f:
        return {(p.ticker, p.date): p for p in parse_lines(f)}


def test_keeps_only_spot_market_quotes() -> None:
    tickers = {ticker for ticker, _ in _points()}

    assert tickers == {"PETR4", "HGLG11", "BOVA11", "OLDC3", "BADP3"}


def test_prices_are_exact_decimal_strings() -> None:
    p = _points()[("PETR4", "2026-09-29")]

    assert (p.open, p.high, p.low, p.close) == ("38.34", "39.00", "38.30", "38.95")
    assert p.volume == "928800000.00"
    assert p.trades == "40001"
    assert p.name == "PETROBRAS PN N2"
    assert p.bdi_code == "02"
    assert p.isin == "BRPETRACNPR6"


def test_quote_factor_gives_unit_price() -> None:
    p = _points()[("OLDC3", "2026-09-29")]

    assert p.close == "12.34567"


def test_malformed_price_becomes_none() -> None:
    p = _points()[("BADP3", "2026-09-29")]

    assert p.close is None
    assert p.open == "1.00"


def test_parse_zip_reads_single_member() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("COTAHIST_A2026.TXT", FIXTURE.read_bytes())

    points = list(parse_zip(buf.getvalue()))

    assert len(points) == 6


def test_canonical_code() -> None:
    assert canonical_code("PETR4") == "B3:PETR4"


def test_ingest_is_idempotent(tmp_path, monkeypatch) -> None:
    from brindex_ingest import main
    from brindex_ingest.db import connect
    from brindex_ingest.sources import b3

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("COTAHIST_A2026.TXT", FIXTURE.read_bytes())
    monkeypatch.setattr(b3, "download", lambda year, session=None: buf.getvalue())

    conn = connect(tmp_path / "db.sqlite")
    main._ingest_b3(conn, [2026])
    main._ingest_b3(conn, [2026])

    assert conn.execute("SELECT COUNT(*) FROM points").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM series WHERE domain = 'b3'").fetchone()[0] == 5
    assert conn.execute(
        "SELECT value FROM points WHERE series_code = 'B3:PETR4' AND date = '2026-09-29'"
    ).fetchone()[0] == "38.95"
