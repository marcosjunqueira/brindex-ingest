import json
from decimal import Decimal
from pathlib import Path

from brindex_ingest.sources.ptax import BUY_CODE, SELL_CODE, _parse_ptax_payload

FIXTURE = Path(__file__).parent / "fixtures" / "ptax_sample.json"


def _load_payload() -> dict:
    return json.loads(FIXTURE.read_text(), parse_float=Decimal)


def test_parses_two_points_per_day() -> None:
    points = _parse_ptax_payload(_load_payload())
    assert len(points) == 4

    dates = {p.date for p in points}
    assert dates == {"2026-09-08", "2026-09-09"}

    codes = {p.code for p in points}
    assert codes == {BUY_CODE, SELL_CODE}


def test_values_are_clean_decimal_strings() -> None:
    points = _parse_ptax_payload(_load_payload())
    values = {(p.code, p.date): p.value for p in points}

    assert values[(BUY_CODE, "2026-09-08")] == "5.08500"
    assert values[(SELL_CODE, "2026-09-08")] == "5.08560"
    assert values[(BUY_CODE, "2026-09-09")] == "5.09730"
    assert values[(SELL_CODE, "2026-09-09")] == "5.09790"

    for value in values.values():
        assert "e" not in value.lower()


def test_money_boundary_non_numeric_value_becomes_none() -> None:
    payload = json.loads(
        '{"value": [{"cotacaoCompra": "N/A", "cotacaoVenda": 5.0860, '
        '"dataHoraCotacao": "2026-09-08 13:02:38.447299"}]}',
        parse_float=Decimal,
    )
    points = _parse_ptax_payload(payload)
    by_code = {p.code: p.value for p in points}

    assert by_code[BUY_CODE] is None
    assert by_code[SELL_CODE] == "5.0860"


def test_money_boundary_nan_becomes_none() -> None:
    payload = json.loads(
        '{"value": [{"cotacaoCompra": NaN, "cotacaoVenda": Infinity, '
        '"dataHoraCotacao": "2026-09-08 13:02:38.447299"}]}',
        parse_float=Decimal,
    )
    points = _parse_ptax_payload(payload)
    by_code = {p.code: p.value for p in points}

    assert by_code[BUY_CODE] is None
    assert by_code[SELL_CODE] is None


def test_malformed_entry_is_skipped_not_fatal() -> None:
    payload = {"value": [{"cotacaoCompra": 5.0}]}
    assert _parse_ptax_payload(payload) == []
