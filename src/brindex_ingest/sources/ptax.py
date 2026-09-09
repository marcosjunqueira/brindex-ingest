"""PTAX (USD reference rate) source: BCB Olinda OData API.

Same endpoint family already used in production by cornerstone-app
(`cornerstone-app/src/storage/bcb.ts`, `CotacaoDolarPeriodo`), reused here
server-side instead of client-side.
"""

from __future__ import annotations

BUY_CODE = "PTAX:USD:BUY"
SELL_CODE = "PTAX:USD:SELL"


def download_and_normalize(start_date: str, end_date: str):
    """TODO: implement. GET the Olinda PTAX OData endpoint for the date range,
    emit one point per day per (buy, sell) pair. Missing/holiday days simply
    produce no row for that date — never a zero or an interpolated value.
    """
    raise NotImplementedError
