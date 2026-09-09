"""Tesouro Direto (Brazilian Treasury Direct) source: downloads the official CDN XLS
files and normalizes each maturity's daily history into
(series_code, date, value, extra_values) rows.

CDN: https://cdn.tesouro.gov.br/sistemas-internos/apex/producao/sistemas/sistd/{year}/{type}_{year}.xls
Confirmed format (2026-09-09): legacy BIFF `.xls` (Excel 2003), read with `xlrd`
(NOT `openpyxl`, which only reads `.xlsx`). Each sheet name encodes series+maturity
("LFT 010326" = LFT maturing 2026-03-01) and cell (0, 1) carries the same maturity
date explicitly ("Vencimento" / "01/03/2026" — "maturity date" in Portuguese, the
literal header the source publishes) — use the cell, not a parse of the sheet name,
as the source of truth for the date.

Tesouro Direto has genuinely distinct prices to invest (buy) and to redeem (sell), so
each row of the source yields two points, one per side — see canonical_code().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import requests
import xlrd

from brindex_ingest.decimal_utils import scale_and_format

logger = logging.getLogger(__name__)

# Keys are the literal CDN URL/file-name tokens (Portuguese, as published by the
# source); values are the series ticker used in our own identity scheme.
TYPES = {
    "LFT": "LFT",
    "LTN": "LTN",
    "NTN-B_Principal": "NTNB-PRINCIPAL",
}

CDN_URL_TEMPLATE = (
    "https://cdn.tesouro.gov.br/sistemas-internos/apex/producao/sistemas/sistd/"
    "{year}/{url_token}_{year}.xls"
)

Side = Literal["BUY", "SELL"]

# Decimal places matching the XLS's own number formats (confirmed 2026-09-09): rate
# columns are formatted "0.00%" but carry more implied precision than that 2-decimal
# display, price columns are formatted "#,##0.00".
_RATE_DECIMALS = 6
_PRICE_DECIMALS = 2


@dataclass(frozen=True)
class TreasuryPoint:
    series: str  # 'LFT' | 'LTN' | 'NTNB-PRINCIPAL'
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


def _parse_date(cell_value: str) -> str:
    """`DD/MM/YYYY` (the source's literal format) -> `YYYY-MM-DD`."""
    return datetime.strptime(cell_value, "%d/%m/%Y").strftime("%Y-%m-%d")


def _parse_row(row_values: list, series: str, maturity: str) -> list[TreasuryPoint]:
    """Normalize one data row (`Dia` [day], `Taxa Compra Manhã` [morning buy rate],
    `Taxa Venda Manhã` [morning sell rate], `PU Compra Manhã` [morning buy unit price],
    `PU Venda Manhã` [morning sell unit price], `PU Base Manhã` [morning base unit price])
    into a BUY and a SELL point. Never raises on a malformed cell — `scale_and_format`
    turns it into `None`, per the money-boundary requirement (SPEC_INGESTION.md §6).
    """
    day_raw, buy_rate, sell_rate, buy_price, sell_price, base_price = row_values[:6]
    date = _parse_date(day_raw)
    base = scale_and_format(base_price, _PRICE_DECIMALS)
    return [
        TreasuryPoint(
            series=series,
            maturity=maturity,
            date=date,
            side="BUY",
            price=scale_and_format(buy_price, _PRICE_DECIMALS),
            rate=scale_and_format(buy_rate, _RATE_DECIMALS),
            base_price=base,
        ),
        TreasuryPoint(
            series=series,
            maturity=maturity,
            date=date,
            side="SELL",
            price=scale_and_format(sell_price, _PRICE_DECIMALS),
            rate=scale_and_format(sell_rate, _RATE_DECIMALS),
            base_price=base,
        ),
    ]


def _parse_sheet(sheet: xlrd.sheet.Sheet, series: str) -> list[TreasuryPoint]:
    """Parse one sheet (one maturity) end to end. A malformed row is logged and
    skipped — it must never abort the rest of the sheet. Likewise a malformed maturity
    header (cell (0, 1)) skips only this sheet, not the whole download.
    """
    try:
        maturity = _parse_date(sheet.cell_value(0, 1))
    except Exception:
        logger.warning(
            "treasury: skipping sheet %r with malformed maturity cell (0,1): %r",
            sheet.name,
            sheet.cell_value(0, 1),
        )
        return []
    points: list[TreasuryPoint] = []
    for row_index in range(2, sheet.nrows):
        row_values = sheet.row_values(row_index)
        try:
            points.extend(_parse_row(row_values, series, maturity))
        except Exception:
            logger.warning(
                "treasury: skipping malformed row %d in sheet %r: %r",
                row_index,
                sheet.name,
                row_values,
            )
    return points


def download_and_normalize(
    year: int, session: requests.Session | None = None
) -> list[TreasuryPoint]:
    """Download every Tesouro Direto XLS for `year` and normalize all sheets into points.
    A single `Session` is reused across all 3 downloads (same CDN host) to avoid a fresh
    TCP+TLS handshake per file. Each of the 3 XLS types is independent: a download/parse
    failure on one type is logged and skipped rather than discarding the other two.
    """
    http = session or requests.Session()
    points: list[TreasuryPoint] = []
    for url_token, series in TYPES.items():
        url = CDN_URL_TEMPLATE.format(year=year, url_token=url_token)
        try:
            response = http.get(url, timeout=30)
            response.raise_for_status()
            workbook = xlrd.open_workbook(file_contents=response.content)
        except Exception:
            logger.warning(
                "treasury: skipping %s (year %d) — download/parse failed",
                url_token,
                year,
                exc_info=True,
            )
            continue
        for sheet in workbook.sheets():
            points.extend(_parse_sheet(sheet, series))
    return points
