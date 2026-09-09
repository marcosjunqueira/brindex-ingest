"""CDI source: BCB SGS API, series 4391.

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
from datetime import datetime
from decimal import Decimal

import requests

logger = logging.getLogger(__name__)

CODE = "CDI:SGS:4391"

_SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.4391/dados"


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
            date = datetime.strptime(entry["data"], "%d/%m/%Y").strftime("%Y-%m-%d")
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
    payload = json.loads(response.text, parse_float=Decimal)
    return _parse_cdi_payload(payload)
