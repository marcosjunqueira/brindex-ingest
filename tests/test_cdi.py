import json
from pathlib import Path

from brindex_ingest.sources.cdi import _parse_cdi_payload, _windows, download_and_normalize

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


def test_windows_split_long_ranges_under_ten_years() -> None:
    windows = _windows("2016-01-01", "2026-10-17")

    assert windows[0][0].isoformat() == "2016-01-01"
    assert windows[-1][1].isoformat() == "2026-10-17"
    assert len(windows) == 2
    for start, end in windows:
        assert (end - start).days < 3650
    # Consecutive and non-overlapping.
    assert (windows[1][0] - windows[0][1]).days == 1


def test_short_range_is_one_window() -> None:
    assert len(_windows("2026-09-17", "2026-10-17")) == 1


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict, timeout: int) -> _FakeResponse:
        self.calls.append((url, params))
        return _FakeResponse(json.dumps([{"data": params["dataFinal"], "valor": "0.055131"}]))


def test_daily_series_backfill_queries_each_window() -> None:
    session = _FakeSession()

    points = download_and_normalize("2016-01-01", "2026-10-17", series=12, session=session)

    assert len(session.calls) == 2
    assert all("bcdata.sgs.12/" in url for url, _ in session.calls)
    assert session.calls[0][1]["dataInicial"] == "01/01/2016"
    assert session.calls[-1][1]["dataFinal"] == "17/10/2026"
    assert [p.value for p in points] == ["0.055131", "0.055131"]
