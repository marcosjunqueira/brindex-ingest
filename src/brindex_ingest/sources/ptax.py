"""PTAX (USD reference rate) source: BCB Olinda OData API.

Same endpoint family already used in production by cornerstone-app
(`cornerstone-app/src/storage/bcb.ts`, `CotacaoDolarPeriodo`), reused here
server-side instead of client-side.

Confirmed live (2026-09-09): `CotacaoDolarPeriodo` returns
`{"value": [{"cotacaoCompra": 5.08500, "cotacaoVenda": 5.08560,
"dataHoraCotacao": "2026-09-08 13:02:38.447299"}, ...]}` — dates in the query string are
`MM-DD-YYYY`, `dataHoraCotacao` in the response is `YYYY-MM-DD HH:MM:SS.ffffff`.
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

BUY_CODE = "PTAX:USD:BUY"
SELL_CODE = "PTAX:USD:SELL"

_ODATA_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)


@dataclass(frozen=True)
class PtaxPoint:
    code: str  # BUY_CODE | SELL_CODE
    date: str  # ISO date, YYYY-MM-DD
    value: str | None


def _clean_rate(value: object) -> str | None:
    """`None`/blank/non-numeric becomes `None`. Also guards `NaN`/`Infinity`: those JSON
    tokens aren't intercepted by `parse_float=Decimal` (they go through `parse_constant`
    as plain `float`s instead), so without this check they'd be stored as the literal
    string `"nan"`/`"inf"` — exactly the sentinel SPEC_INGESTION.md §6 forbids.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, float):
        return str(value) if math.isfinite(value) else None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return str(value) if math.isfinite(numeric) else None


def _parse_ptax_payload(payload: dict) -> list[PtaxPoint]:
    """Normalize an already-decoded Olinda response (decoded with
    `json.loads(text, parse_float=Decimal)` so buy/sell rates never touch `float`).
    """
    points: list[PtaxPoint] = []
    for entry in payload.get("value", []):
        try:
            date = entry["dataHoraCotacao"].split(" ")[0]
        except (KeyError, AttributeError, TypeError):
            logger.warning("ptax: skipping malformed entry: %r", entry)
            continue
        buy = entry.get("cotacaoCompra")
        sell = entry.get("cotacaoVenda")
        points.append(PtaxPoint(code=BUY_CODE, date=date, value=_clean_rate(buy)))
        points.append(PtaxPoint(code=SELL_CODE, date=date, value=_clean_rate(sell)))
    return points


def download_and_normalize(
    start_date: str, end_date: str, session: requests.Session | None = None
) -> list[PtaxPoint]:
    """GET the Olinda PTAX OData endpoint for `[start_date, end_date]` (ISO dates) and emit
    one point per day per (buy, sell) side. Missing/holiday days simply produce no row for
    that date — never a zero or an interpolated value.
    """
    http = session or requests
    params_start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%m-%d-%Y")
    params_end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%m-%d-%Y")
    response = http.get(
        _ODATA_URL,
        params={
            "@dataInicial": f"'{params_start}'",
            "@dataFinalCotacao": f"'{params_end}'",
            "$format": "json",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = json.loads(response.text, parse_float=Decimal)
    return _parse_ptax_payload(payload)
