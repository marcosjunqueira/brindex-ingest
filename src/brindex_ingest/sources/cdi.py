"""CDI source: BCB SGS API, series 4391 (monthly) and 12 (daily).

Same endpoint already used in production by cornerstone-app
(`cornerstone-app/src/storage/bcb.ts`), reused here server-side.

Confirmed live (2026-09-09): returns `[{"data": "01/09/2026", "valor": "0.26"}, ...]` —
`valor` is already a JSON string, so no `float` ever enters this pipeline.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

import requests

logger = logging.getLogger(__name__)

CODE = "CDI:SGS:4391"  # monthly, % per month
DAILY_CODE = "CDI:SGS:12"  # daily (business days), % per day

# (SGS series number, display name) per code, in ingestion order.
SERIES = {CODE: (4391, "CDI"), DAILY_CODE: (12, "CDI daily")}

_SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series}/dados"

# The SGS API rejects a query on a daily series spanning more than 10 years, so every
# request is split into windows shorter than that (3650 days < 10 years, leap days included).
_MAX_WINDOW_DAYS = 3650


@dataclass(frozen=True)
class CdiPoint:
    date: str  # ISO date, YYYY-MM-DD
    value: str | None


def _parse_cdi_payload(payload: list[dict]) -> list[CdiPoint]:
    """Normalize an already-decoded SGS response. `valor` is passed through byte-for-byte
    when it parses as a finite number (never round-tripped through `float` for storage);
    otherwise `None`. A malformed entry (bad/missing date) is logged and skipped rather
    than aborting the whole payload.
    """
    points: list[CdiPoint] = []
    for entry in payload:
        try:
            iso_date = datetime.strptime(entry["data"], "%d/%m/%Y").strftime("%Y-%m-%d")
        except (KeyError, TypeError, ValueError):
            logger.warning("cdi: skipping malformed entry: %r", entry)
            continue
        valor = entry.get("valor")
        try:
            numeric = float(valor)
        except (TypeError, ValueError):
            value = None
        else:
            # `math.isfinite` rejects "nan"/"inf"/"-Infinity" strings, which Python's
            # permissive float() grammar would otherwise accept and store verbatim.
            value = str(valor) if math.isfinite(numeric) else None
        points.append(CdiPoint(date=iso_date, value=value))
    return points


def _windows(start_date: str, end_date: str) -> list[tuple[date, date]]:
    """Split `[start_date, end_date]` (ISO dates, inclusive) into consecutive windows of
    at most `_MAX_WINDOW_DAYS` days each. A reversed range is an error, so a mistyped
    future `--since` fails loudly instead of silently ingesting nothing."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError(f"cdi: start date {start_date} is after end date {end_date}")
    windows = []
    while start <= end:
        window_end = min(start + timedelta(days=_MAX_WINDOW_DAYS - 1), end)
        windows.append((start, window_end))
        start = window_end + timedelta(days=1)
    return windows


def download_and_normalize(
    start_date: str,
    end_date: str,
    series: int,
    session: requests.Session | None = None,
) -> list[CdiPoint]:
    """GET SGS `series` for `[start_date, end_date]` (ISO dates) and emit one point per
    period the source publishes. Series 4391 is monthly (confirmed live 2026-09-09: one
    entry per calendar month, dated the 1st, e.g. `{"data": "01/09/2026", "valor":
    "0.26"}`); series 12 is daily, one entry per business day (% per day). Long ranges
    are fetched in windows, since the API caps daily-series queries at 10 years. A window
    with no data (e.g. only a weekend or holiday) answers 404 and is treated as empty.
    """
    http = session or requests
    points_by_date: dict[str, CdiPoint] = {}
    for window_start, window_end in _windows(start_date, end_date):
        response = http.get(
            _SGS_URL.format(series=series),
            params={
                "formato": "json",
                "dataInicial": window_start.strftime("%d/%m/%Y"),
                "dataFinal": window_end.strftime("%d/%m/%Y"),
            },
            timeout=30,
        )
        if response.status_code == 404:
            logger.info("cdi: SGS %d has no data from %s to %s", series, window_start, window_end)
            continue
        response.raise_for_status()
        payload = json.loads(response.text, parse_float=Decimal)
        # Keep only points inside the window, one per date, so a boundary point the API
        # repeats across windows never appears twice in the batch.
        for point in _parse_cdi_payload(payload):
            if window_start.isoformat() <= point.date <= window_end.isoformat():
                points_by_date[point.date] = point
    return sorted(points_by_date.values(), key=lambda p: p.date)
