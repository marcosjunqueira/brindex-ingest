from brindex_ingest.decimal_utils import scale_and_format


def test_eliminates_float_noise_ntnb_rate() -> None:
    # Real value captured from NTN-B_Principal_2026.xls (Taxa Venda Manhã, rate column).
    assert scale_and_format(0.10369999999999999, 6) == "0.103700"


def test_eliminates_float_noise_lft_rate() -> None:
    # Real value captured from LFT_2026.xls (Taxa Compra Manhã, rate column).
    assert scale_and_format(0.0007520000000000001, 6) == "0.000752"


def test_price_column_two_decimals() -> None:
    assert scale_and_format(18105.3, 2) == "18105.30"


def test_negative_value() -> None:
    assert scale_and_format(-12.34, 2) == "-12.34"


def test_blank_cell_is_none() -> None:
    assert scale_and_format("", 2) is None


def test_none_is_none() -> None:
    assert scale_and_format(None, 2) is None


def test_non_numeric_string_is_none() -> None:
    assert scale_and_format("n/a", 2) is None
