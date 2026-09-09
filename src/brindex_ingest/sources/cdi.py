"""CDI source: BCB SGS API, series 4391.

Same endpoint already used in production by cornerstone-app
(`cornerstone-app/src/storage/bcb.ts`), reused here server-side.

Confirmed live (2026-09-09): returns `[{"data": "01/09/2026", "valor": "0.26"}, ...]` —
`valor` is already a JSON string, so no `float` ever enters this pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import requests

CODE = "CDI:SGS:4391"

_SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.4391/dados"


@dataclass(frozen=True)
class CdiPoint:
    date: str  # ISO date, YYYY-MM-DD
    value: str | None


def _parse_cdi_payload(payload: list[dict]) -> list[CdiPoint]:
    """Normalize an already-decoded SGS response. `valor` is passed through byte-for-byte
    when it parses as a number (never round-tripped through `float`); otherwise `None`.
    """
    points: list[CdiPoint] = []
    for entry in payload:
        date = datetime.strptime(entry["data"], "%d/%m/%Y").strftime("%Y-%m-%d")
        valor = entry.get("valor")
        try:
            float(valor)
        except (TypeError, ValueError):
            value = None
        else:
            value = valor
        points.append(CdiPoint(date=date, value=value))
    return points


def download_and_normalize(
    start_date: str, end_date: str, session: requests.Session | None = None
) -> list[CdiPoint]:
    """GET the SGS series for `[start_date, end_date]` (ISO dates) and emit one point per
    period the source publishes. Series 4391 is monthly (confirmed live 2026-09-09: one
    entry per calendar month, dated the 1st, e.g. `{"data": "01/09/2026", "valor":
    "0.26"}`) — not daily, despite the CLI flag being named `--since` in day granularity.
    """
    http = session or requests
    params_start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    params_end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    response = http.get(
        _SGS_URL,
        params={
            "formato": "json",
            "dataInicial": params_start,
            "dataFinal": params_end,
        },
        timeout=30,
    )
    response.raise_for_status()
    return _parse_cdi_payload(response.json())
