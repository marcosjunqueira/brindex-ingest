"""Tesouro Direto (Brazilian Treasury Direct) source: downloads the official
Tesouro Transparente open-data CSV and normalizes every row into
(series_code, date, value, extra_values) points.

CSV: https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv
Dataset: "Taxas dos Títulos Ofertados pelo Tesouro Direto" (CKAN, ODbL license).

**Source changed 2026-09-09** — see SPEC_INGESTION.md §2.1/§2.1a for the full history.
The previously used CDN `.xls` files (one per title type, one sheet per maturity, one
file per calendar year) were found to be stale in production (stuck ~3 weeks behind on
the date the switch was made). This CSV publishes the same underlying numbers — verified
byte-for-byte against overlapping rows of the old `.xls` — as a single flat file covering
every title type and the full history since January 2002, updated daily.

Confirmed format (2026-09-09): `;`-delimited, `latin-1`-encoded, decimal comma (no
thousands separator), one header row with the source's own literal Portuguese column
names: `Tipo Titulo` (title type — a retail product name, NOT this repo's `<SERIES>`
token, see TIPO_TITULO_TO_SERIES), `Data Vencimento` (maturity date, DD/MM/YYYY),
`Data Base` (as-of date, DD/MM/YYYY), `Taxa Compra Manha` / `Taxa Venda Manha` (morning
buy/sell rate), `PU Compra Manha` / `PU Venda Manha` (morning buy/sell unit price),
`PU Base Manha` (morning base unit price).

Tesouro Direto has genuinely distinct prices to invest (buy) and to redeem (sell), so
each row of the source yields two points, one per side — see canonical_code().
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

import requests

from brindex_ingest.decimal_utils import scale_and_format

logger = logging.getLogger(__name__)

# Maps the source's literal `Tipo Titulo` retail product name (Portuguese, as published
# in the CSV) to the series ticker used in our own identity scheme. `Tesouro IPCA+` (no
# coupon) and `Tesouro IPCA+ com Juros Semestrais` (semiannual coupon) can share the same
# `Data Vencimento` while being different instruments with materially different prices —
# they must never be conflated (SPEC_INGESTION.md §3.1a).
TIPO_TITULO_TO_SERIES = {
    "Tesouro Selic": "LFT",
    "Tesouro Prefixado": "LTN",
    "Tesouro Prefixado com Juros Semestrais": "NTNF",
    "Tesouro IPCA+": "NTNB-PRINCIPAL",
    "Tesouro IPCA+ com Juros Semestrais": "NTNB",
}

# Popular product names as printed on an actual Tesouro Direto trade note (source's own
# literal Portuguese product names, kept verbatim per CLAUDE.md's literal-value
# convention) — the inverse of TIPO_TITULO_TO_SERIES, keyed by series ticker.
SERIES_POPULAR_NAME = {series: tipo for tipo, series in TIPO_TITULO_TO_SERIES.items()}

CSV_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)

Side = Literal["BUY", "SELL"]

# Decimal places matching the source's own number formats (confirmed 2026-09-09,
# unchanged from the superseded .xls source): rate columns carry more implied precision
# than their 2-decimal display, price columns are "#,##0.00".
_RATE_DECIMALS = 6
_PRICE_DECIMALS = 2


@dataclass(frozen=True)
class TreasuryPoint:
    series: str  # 'LFT' | 'LTN' | 'NTNB-PRINCIPAL' | 'NTNB' | 'NTNF'
    maturity: str  # ISO date, YYYY-MM-DD
    date: str  # ISO date, YYYY-MM-DD
    side: Side
    price: str | None
    rate: str | None
    base_price: str | None


def canonical_code(series: str, maturity: str, side: Side) -> str:
    """`TD:<SERIES>:<YYYY-MM-DD>:<SIDE>` — one series per maturity per side (BUY/SELL),
    since Tesouro Direto publishes genuinely distinct invest and redeem prices."""
    return f"TD:{series}:{maturity}:{side}"


def display_name(series: str, maturity: str, side: Side) -> str:
    """Human-readable series name, e.g. "Tesouro Selic 2031-03-01 (LFT, BUY)"."""
    return f"{SERIES_POPULAR_NAME[series]} {maturity} ({series}, {side})"


def _parse_date(value: str) -> str:
    """`DD/MM/YYYY` (the source's literal format) -> `YYYY-MM-DD`."""
    return datetime.strptime(value, "%d/%m/%Y").strftime("%Y-%m-%d")


def _parse_decimal(value: str, decimals: int, *, scale: int = 1) -> str | None:
    """Brazilian decimal-comma string (e.g. `"19830,70"`) -> fixed-`decimals` decimal
    string, or `None` if blank/non-numeric. A blank cell becomes SQL NULL, never a
    crash or a sentinel (SPEC_INGESTION.md §6) — `scale_and_format` already handles
    that once the comma is normalized to a dot.

    `scale` divides the parsed value before quantizing (via `Decimal`, so the division
    itself is exact for a power-of-10 divisor). This project's rate convention — set by
    the superseded `.xls` source and unchanged since — stores rates as a fraction of 1
    (e.g. `0.0772` for 7.72%), but this CSV publishes `Taxa Compra/Venda Manha` as a raw
    percentage-point number (e.g. `"7,72"`, confirmed 2026-09-09 by cross-checking the
    same title/maturity/date against the old `.xls`: CSV `7,97` == XLS fraction `0.0796`,
    a 100x difference) — callers parsing a rate column must pass `scale=100` to preserve
    the established convention instead of silently storing a value 100x too large.
    """
    if value is None:
        return None
    normalized = value.replace(",", ".").strip()
    if normalized == "":
        return None
    try:
        numeric = Decimal(normalized) / scale
    except InvalidOperation:
        return None
    return scale_and_format(numeric, decimals)


def _parse_row(row: dict[str, str]) -> list[TreasuryPoint] | None:
    """Normalize one CSV row into a BUY and a SELL point, or `None` if the row's `Tipo
    Titulo` has no `<SERIES>` mapping yet (SPEC_INGESTION.md §3.1a — logged once per
    distinct unmapped type by the caller, not here, to avoid 100k+ duplicate log lines).
    Never raises on a malformed price/rate cell — `_parse_decimal` turns it into `None`.
    """
    series = TIPO_TITULO_TO_SERIES.get(row["Tipo Titulo"])
    if series is None:
        return None
    maturity = _parse_date(row["Data Vencimento"])
    date = _parse_date(row["Data Base"])
    base = _parse_decimal(row["PU Base Manha"], _PRICE_DECIMALS)
    return [
        TreasuryPoint(
            series=series,
            maturity=maturity,
            date=date,
            side="BUY",
            price=_parse_decimal(row["PU Compra Manha"], _PRICE_DECIMALS),
            rate=_parse_decimal(row["Taxa Compra Manha"], _RATE_DECIMALS, scale=100),
            base_price=base,
        ),
        TreasuryPoint(
            series=series,
            maturity=maturity,
            date=date,
            side="SELL",
            price=_parse_decimal(row["PU Venda Manha"], _PRICE_DECIMALS),
            rate=_parse_decimal(row["Taxa Venda Manha"], _RATE_DECIMALS, scale=100),
            base_price=base,
        ),
    ]


def _parse_csv(csv_text: str) -> list[TreasuryPoint]:
    """Parse the full CSV (already decoded to `str`) end to end. A malformed row is
    logged and skipped — it must never abort the rest of the file. An unmapped `Tipo
    Titulo` is skipped too (see _parse_row), with one warning per distinct type.
    """
    points: list[TreasuryPoint] = []
    unmapped_types: set[str] = set()
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
    for row in reader:
        try:
            row_points = _parse_row(row)
        except Exception:
            logger.warning("treasury: skipping malformed row: %r", row, exc_info=True)
            continue
        if row_points is None:
            tipo = row.get("Tipo Titulo")
            if tipo not in unmapped_types:
                unmapped_types.add(tipo)
                logger.warning(
                    "treasury: skipping rows with unmapped Tipo Titulo %r — "
                    "no <SERIES> token yet, see SPEC_INGESTION.md §3.1a",
                    tipo,
                )
            continue
        points.extend(row_points)
    return points


def download_and_normalize(session: requests.Session | None = None) -> list[TreasuryPoint]:
    """Download the full Tesouro Transparente CSV and normalize every row into points.
    The file covers every title type and the full history since January 2002 in one
    request — there is no per-year download to fail independently of another, unlike
    the superseded per-type CDN `.xls` files.
    """
    http = session or requests
    response = http.get(CSV_URL, timeout=60)
    response.raise_for_status()
    csv_text = response.content.decode("latin-1")
    return _parse_csv(csv_text)
