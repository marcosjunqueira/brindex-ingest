from pathlib import Path

import xlrd

from brindex_ingest.db import PointRow, connect, upsert_points, upsert_series
from brindex_ingest.sources import treasury

FIXTURES = Path(__file__).parent / "fixtures"


def _parse_fixture(filename: str, sheet_name: str, series: str):
    workbook = xlrd.open_workbook(str(FIXTURES / filename))
    sheet = workbook.sheet_by_name(sheet_name)
    return treasury._parse_sheet(sheet, series)


def test_lft_fixture_yields_buy_and_sell_per_row() -> None:
    points = _parse_fixture("LFT_2026.xls", "LFT 010326", "LFT")
    workbook = xlrd.open_workbook(str(FIXTURES / "LFT_2026.xls"))
    sheet = workbook.sheet_by_name("LFT 010326")
    data_rows = sheet.nrows - 2
    assert len(points) == data_rows * 2


def test_lft_fixture_first_row_values() -> None:
    points = _parse_fixture("LFT_2026.xls", "LFT 010326", "LFT")
    buy, sell = points[0], points[1]

    assert buy.maturity == "2026-03-01"
    assert buy.date == "2026-01-02"
    assert buy.side == "BUY"
    assert buy.price == "18105.30"
    assert buy.base_price == "18094.98"

    assert sell.date == "2026-01-02"
    assert sell.side == "SELL"
    assert sell.price == "18094.98"
    assert sell.base_price == "18094.98"


def test_canonical_code_distinguishes_sides() -> None:
    buy_code = treasury.canonical_code("LFT", "2026-03-01", "BUY")
    sell_code = treasury.canonical_code("LFT", "2026-03-01", "SELL")
    assert buy_code != sell_code
    assert buy_code == "TD:LFT:2026-03-01:BUY"
    assert sell_code == "TD:LFT:2026-03-01:SELL"


def test_ltn_and_ntnb_fixtures_parse_without_error() -> None:
    ltn_points = _parse_fixture("LTN_2026.xls", "LTN 010127", "LTN")
    ntnb_points = _parse_fixture(
        "NTN-B_Principal_2026.xls", "NTN-B Princ 150826", "NTNB-PRINCIPAL"
    )
    assert len(ltn_points) > 0
    assert len(ntnb_points) > 0


def test_ntnb_and_ntnf_fixtures_parse_without_error() -> None:
    ntnb_points = _parse_fixture("NTN-B_2026.xls", "NTN-B 150826", "NTNB")
    ntnf_points = _parse_fixture("NTN-F_2026.xls", "NTN-F 010127", "NTNF")
    assert len(ntnb_points) > 0
    assert len(ntnf_points) > 0
    assert ntnb_points[0].series == "NTNB"
    assert ntnb_points[0].maturity == "2026-08-15"
    assert ntnf_points[0].series == "NTNF"
    assert ntnf_points[0].maturity == "2027-01-01"


def test_every_series_has_a_popular_name() -> None:
    assert set(treasury.SERIES_POPULAR_NAME) == set(treasury.TYPES.values())


def test_display_name_format() -> None:
    assert (
        treasury.display_name("LFT", "2031-03-01", "BUY")
        == "Tesouro Selic 2031-03-01 (LFT, BUY)"
    )


def test_money_boundary_blank_cell_becomes_none() -> None:
    row = ["02/01/2026", "", 0.000264, 18105.3, "", 18094.98]
    buy, sell = treasury._parse_row(row, "LFT", "2026-03-01")

    assert buy.rate is None
    assert buy.price == "18105.30"
    assert sell.price is None
    assert sell.rate == "0.000264"


def test_idempotent_upsert(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.sqlite")
    points = _parse_fixture("LFT_2026.xls", "LFT 010326", "LFT")[:2]

    def to_rows(pts):
        for p in pts:
            code = treasury.canonical_code(p.series, p.maturity, p.side)
            upsert_series(
                conn, code, "treasury-direct", "n", {"maturity": p.maturity}, "2026-01-01"
            )
            yield PointRow(code, p.date, p.price, None, "2026-01-01T00:00:00Z")

    upsert_points(conn, to_rows(points))
    conn.commit()
    count_first = conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]

    upsert_points(conn, to_rows(points))
    conn.commit()
    count_second = conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]

    assert count_first == count_second == 2

    revised = [points[0].__class__(**{**points[0].__dict__, "price": "99999.99"})]
    upsert_points(
        conn,
        [
            PointRow(
                treasury.canonical_code(revised[0].series, revised[0].maturity, revised[0].side),
                revised[0].date,
                revised[0].price,
                None,
                "2026-01-02T00:00:00Z",
            )
        ],
    )
    conn.commit()
    updated_value = conn.execute(
        "SELECT value FROM points WHERE series_code = ? AND date = ?",
        (
            treasury.canonical_code(points[0].series, points[0].maturity, points[0].side),
            points[0].date,
        ),
    ).fetchone()[0]
    assert updated_value == "99999.99"
    count_third = conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]
    assert count_third == 2
