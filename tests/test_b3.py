import io
import zipfile
from pathlib import Path

from brindex_ingest.sources.b3 import canonical_code, parse_lines, parse_zip

# Synthetic records built from B3's published COTAHIST layout (SPEC_INGESTION.md §2.2); the
# real annual file (~80-90 MB) is too large to commit. The parser was verified against the
# real 2026 file separately (see §2.2).
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
    main._ingest_b3(conn, [2026], 2026)
    main._ingest_b3(conn, [2026], 2026)

    assert conn.execute("SELECT COUNT(*) FROM points").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM series WHERE domain = 'b3'").fetchone()[0] == 5
    assert conn.execute(
        "SELECT value FROM points WHERE series_code = 'B3:PETR4' AND date = '2026-09-29'"
    ).fetchone()[0] == "38.95"


def _http_error(status: int):
    import requests

    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def test_current_year_not_published_yet_is_skipped(tmp_path, monkeypatch) -> None:
    from brindex_ingest import main
    from brindex_ingest.db import connect
    from brindex_ingest.sources import b3

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("COTAHIST_A2026.TXT", FIXTURE.read_bytes())

    def fake_download(year, session=None):
        if year == 2027:
            raise _http_error(404)
        return buf.getvalue()

    monkeypatch.setattr(b3, "download", fake_download)
    conn = connect(tmp_path / "db.sqlite")
    main._ingest_b3(conn, [2026, 2027], 2027)

    assert conn.execute("SELECT COUNT(*) FROM points").fetchone()[0] == 6


def test_missing_past_year_still_fails(tmp_path, monkeypatch) -> None:
    import pytest
    import requests

    from brindex_ingest import main
    from brindex_ingest.db import connect
    from brindex_ingest.sources import b3

    def fake_download(year, session=None):
        raise _http_error(404)

    monkeypatch.setattr(b3, "download", fake_download)
    conn = connect(tmp_path / "db.sqlite")
    with pytest.raises(requests.HTTPError):
        main._ingest_b3(conn, [2025], 2026)
