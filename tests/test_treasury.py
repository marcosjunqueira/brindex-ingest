from pathlib import Path

from brindex_ingest.db import PointRow, connect, upsert_points, upsert_series
from brindex_ingest.sources import treasury

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_CSV = (FIXTURES / "precotaxatesourodireto_sample.csv").read_text(encoding="latin-1")


def test_sample_csv_yields_buy_and_sell_per_mapped_row() -> None:
    points = treasury._parse_csv(SAMPLE_CSV)
    # 8 data rows, 1 unmapped (Tesouro Educa+) skipped -> 7 mapped rows * 2 sides
    assert len(points) == 14


def test_first_row_values() -> None:
    points = treasury._parse_csv(SAMPLE_CSV)
    buy, sell = points[0], points[1]

    assert buy.series == "LFT"
    assert buy.maturity == "2028-03-01"
    assert buy.date == "2026-08-31"
    assert buy.side == "BUY"
    assert buy.price == "19780.33"
    assert buy.rate == "0.000100"  # source "0,01" is a percentage-point figure -> /100
    assert buy.base_price == "19767.10"

    assert sell.side == "SELL"
    assert sell.price == "19767.10"
    assert sell.rate == "0.000200"  # source "0,02" -> /100


def test_unmapped_tipo_titulo_is_skipped() -> None:
    points = treasury._parse_csv(SAMPLE_CSV)
    assert all(p.series != "Tesouro Educa+" for p in points)
    codes = {treasury.canonical_code(p.series, p.maturity, p.side) for p in points}
    assert not any("Educa" in c for c in codes)


def test_canonical_code_distinguishes_sides() -> None:
    buy_code = treasury.canonical_code("LFT", "2026-03-01", "BUY")
    sell_code = treasury.canonical_code("LFT", "2026-03-01", "SELL")
    assert buy_code != sell_code
    assert buy_code == "TD:LFT:2026-03-01:BUY"
    assert sell_code == "TD:LFT:2026-03-01:SELL"


def test_every_series_has_a_popular_name() -> None:
    assert set(treasury.SERIES_POPULAR_NAME) == set(treasury.TIPO_TITULO_TO_SERIES.values())


def test_display_name_format() -> None:
    assert (
        treasury.display_name("LFT", "2031-03-01", "BUY")
        == "Tesouro Selic 2031-03-01 (LFT, BUY)"
    )


def test_all_five_mapped_series_are_present_in_sample() -> None:
    points = treasury._parse_csv(SAMPLE_CSV)
    assert {p.series for p in points} == {"LFT", "LTN", "NTNF", "NTNB-PRINCIPAL", "NTNB"}


def test_rate_is_converted_from_source_percentage_points_to_a_fraction() -> None:
    # The CSV publishes "Taxa Compra/Venda Manha" as a raw percentage-point figure
    # (e.g. "7,72" meaning 7.72%), but this repo's established convention (matching the
    # superseded .xls source and every already-stored rate) is a fraction of 1
    # (0.0772) — regression test for the 100x scale bug found during code review.
    points = treasury._parse_csv(SAMPLE_CSV)
    ntnb_principal_buy = next(
        p for p in points if p.series == "NTNB-PRINCIPAL" and p.side == "BUY"
    )
    assert ntnb_principal_buy.rate == "0.077200"  # source "7,72" -> /100


def test_money_boundary_blank_cells_become_none() -> None:
    points = treasury._parse_csv(SAMPLE_CSV)
    last_buy, last_sell = points[-2], points[-1]

    assert last_buy.date == "2026-09-09"
    assert last_buy.rate is None  # blank "Taxa Compra Manha"
    assert last_buy.price == "19830.70"
    assert last_sell.price is None  # blank "PU Venda Manha"
    assert last_sell.rate == "0.000200"  # source "0,02" -> /100
    assert last_buy.base_price == "19817.48"


def test_idempotent_upsert(tmp_path: Path) -> None:
    conn = connect(tmp_path / "test.sqlite")
    points = treasury._parse_csv(SAMPLE_CSV)[:2]

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
