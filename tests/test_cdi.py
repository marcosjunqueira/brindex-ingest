import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import requests

from brindex_ingest.db import connect
from brindex_ingest.main import _ingest_cdi
from brindex_ingest.sources import cdi
from brindex_ingest.sources.cdi import _parse_cdi_payload, _windows, download_and_normalize

FIXTURE = Path(__file__).parent / "fixtures" / "cdi_sample.json"
DAILY_FIXTURE = Path(__file__).parent / "fixtures" / "cdi12_sample.json"


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
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class _FakeSession:
    """Answers each window with `payload` (filtered to the window), or 404 when empty,
    which is how SGS answers a window with no data."""

    def __init__(self, payload: list[dict]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict, timeout: int) -> _FakeResponse:
        self.calls.append((url, params))
        start = datetime.strptime(params["dataInicial"], "%d/%m/%Y")
        end = datetime.strptime(params["dataFinal"], "%d/%m/%Y")
        entries = [e for e in self.payload if start <= datetime.strptime(e["data"], "%d/%m/%Y") <= end]
        if not entries:
            return _FakeResponse('{"error": "no data"}', status_code=404)
        return _FakeResponse(json.dumps(entries))


def test_daily_series_backfill_queries_each_window() -> None:
    session = _FakeSession(
        [{"data": "04/01/2016", "valor": "0.052531"}, {"data": "16/10/2026", "valor": "0.055131"}]
    )

    points = download_and_normalize("2016-01-01", "2026-10-17", series=12, session=session)

    assert len(session.calls) == 2
    assert all("bcdata.sgs.12/" in url for url, _ in session.calls)
    assert session.calls[0][1]["dataInicial"] == "01/01/2016"
    assert session.calls[-1][1]["dataFinal"] == "17/10/2026"
    assert [(p.date, p.value) for p in points] == [
        ("2016-01-04", "0.052531"),
        ("2026-10-16", "0.055131"),
    ]


def test_empty_one_day_final_window_is_not_an_error() -> None:
    # 3650 + 1 days: the final window is a single Saturday with no data (SGS answers 404).
    end = date(2026, 10, 17)
    start = end - timedelta(days=3650)
    assert end.weekday() == 5
    session = _FakeSession([{"data": "22/10/2016", "valor": "0.051"}])

    points = download_and_normalize(start.isoformat(), end.isoformat(), series=12, session=session)

    assert len(session.calls) == 2
    assert [p.date for p in points] == ["2016-10-22"]


def test_point_repeated_across_windows_is_kept_once() -> None:
    class _BoundarySession(_FakeSession):
        def get(self, url, params, timeout):
            self.calls.append((url, params))
            # Always returns the same point, even for windows that do not contain it.
            return _FakeResponse(json.dumps(self.payload))

    session = _BoundarySession([{"data": "01/01/2026", "valor": "1.16"}])

    points = download_and_normalize("2016-01-01", "2026-10-17", series=4391, session=session)

    assert [p.date for p in points] == ["2026-01-01"]


def test_reversed_range_fails_loudly() -> None:
    with pytest.raises(ValueError):
        _windows("2026-10-18", "2026-10-17")


def _fake_get(payloads: dict[int, list[dict] | Exception]):
    def get(url: str, params: dict, timeout: int):
        series = int(url.split("bcdata.sgs.")[1].split("/")[0])
        payload = payloads[series]
        if isinstance(payload, Exception):
            raise payload
        return _FakeSession(payload).get(url, params, timeout)

    return get


def test_daily_series_ingestion_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    daily = json.loads(DAILY_FIXTURE.read_text())
    monkeypatch.setattr(cdi.requests, "get", _fake_get({4391: [], 12: daily}))
    conn = connect(tmp_path / "test.sqlite")

    _ingest_cdi(conn, "2026-10-01", "2026-10-17")
    _ingest_cdi(conn, "2026-10-01", "2026-10-17")

    rows = conn.execute(
        "SELECT date, value FROM points WHERE series_code = 'CDI:SGS:12' ORDER BY date"
    ).fetchall()
    assert rows == [("2026-10-14", "0.055131"), ("2026-10-15", "0.055131"), ("2026-10-16", None)]


def test_one_cdi_series_failing_keeps_the_other(tmp_path: Path, monkeypatch) -> None:
    monthly = _load_payload()[:1]
    monkeypatch.setattr(
        cdi.requests, "get", _fake_get({4391: monthly, 12: requests.ConnectionError("down")})
    )
    conn = connect(tmp_path / "test.sqlite")

    with pytest.raises(RuntimeError):
        _ingest_cdi(conn, "2026-09-01", "2026-10-17")

    codes = {row[0] for row in conn.execute("SELECT DISTINCT series_code FROM points")}
    assert codes == {"CDI:SGS:4391"}
