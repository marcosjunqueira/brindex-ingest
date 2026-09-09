import json
from pathlib import Path

from brindex_ingest.sources.cdi import _parse_cdi_payload

FIXTURE = Path(__file__).parent / "fixtures" / "cdi_sample.json"


def _load_payload() -> list[dict]:
    return json.loads(FIXTURE.read_text())


def test_valid_entries_pass_through_unchanged() -> None:
    points = _parse_cdi_payload(_load_payload())
    by_date = {p.date: p.value for p in points}

    assert by_date["2026-09-01"] == "0.26"
    assert by_date["2026-09-02"] == "0.26"


def test_malformed_entry_becomes_none() -> None:
    points = _parse_cdi_payload(_load_payload())
    by_date = {p.date: p.value for p in points}

    assert by_date["2026-09-03"] is None
