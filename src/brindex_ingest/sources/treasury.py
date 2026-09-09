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
"""

from __future__ import annotations

from dataclasses import dataclass

# Keys are the literal CDN URL/file-name tokens (Portuguese, as published by the
# source); values are the series ticker used in our own identity scheme.
TYPES = {
    "LFT": "LFT",
    "LTN": "LTN",
    "NTN-B_Principal": "NTNB-PRINCIPAL",
}


@dataclass(frozen=True)
class TreasuryPoint:
    series: str  # 'LFT' | 'LTN' | 'NTNB-PRINCIPAL'
    maturity: str  # ISO date, YYYY-MM-DD
    date: str  # ISO date, YYYY-MM-DD
    buy_price: str | None
    sell_price: str | None
    base_price: str | None


def canonical_code(series: str, maturity: str) -> str:
    """`TD:<SERIES>:<YYYY-MM-DD>` — the identity scheme shared with `brindex-api`
    and with cornerstone-app's own Tesouro Direto catalog (see
    portfolio-rebalancer/.specs/New/SPEC_TESOURO_DIRETO_CATALOGO_OFICIAL.md)."""
    return f"TD:{series}:{maturity}"


def download_and_normalize(year: int) -> list[TreasuryPoint]:
    """TODO: implement. For each entry in TYPES, download the CDN XLS for `year`,
    open every sheet, read cell (0, 1) for the maturity date, then read each data
    row (columns: Dia [day], Taxa Compra Manhã [morning buy rate], Taxa Venda Manhã
    [morning sell rate], PU Compra Manhã [morning buy unit price], PU Venda Manhã
    [morning sell unit price], PU Base Manhã [morning base unit price]) into a
    TreasuryPoint. Never raise on a single malformed row — skip it, log it, and
    keep processing the rest of the sheet.
    """
    raise NotImplementedError
