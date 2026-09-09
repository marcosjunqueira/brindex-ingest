"""Tesouro Direto source: downloads the official CDN XLS files and normalizes
each maturity's daily history into (serie_codigo, data, valor, valores_extra) rows.

CDN: https://cdn.tesouro.gov.br/sistemas-internos/apex/producao/sistemas/sistd/{ano}/{tipo}_{ano}.xls
Confirmed format (2026-09-09): legacy BIFF `.xls` (Excel 2003), read with `xlrd`
(NOT `openpyxl`, which only reads `.xlsx`). Each sheet name encodes série+vencimento
("LFT 010326" = LFT maturing 2026-03-01) and cell (0, 1) carries the same maturity
date explicitly ("Vencimento" / "01/03/2026") — use the cell, not a parse of the
sheet name, as the source of truth for the date.
"""

from __future__ import annotations

from dataclasses import dataclass

TIPOS = {
    "LFT": "LFT",
    "LTN": "LTN",
    "NTN-B_Principal": "NTNB-PRINCIPAL",
}


@dataclass(frozen=True)
class PontoTesouro:
    serie: str  # 'LFT' | 'LTN' | 'NTNB-PRINCIPAL'
    vencimento: str  # ISO date, YYYY-MM-DD
    data: str  # ISO date, YYYY-MM-DD
    pu_compra: str | None
    pu_venda: str | None
    pu_base: str | None


def codigo_canonico(serie: str, vencimento: str) -> str:
    """`TD:<SERIE>:<AAAA-MM-DD>` — the identity scheme shared with `brindex-api`
    and with cornerstone-app's own Tesouro Direto catalog (see
    portfolio-rebalancer/.specs/New/SPEC_TESOURO_DIRETO_CATALOGO_OFICIAL.md)."""
    return f"TD:{serie}:{vencimento}"


def baixar_e_normalizar(ano: int) -> list[PontoTesouro]:
    """TODO: implement. For each entry in TIPOS, download the CDN XLS for `ano`,
    open every sheet, read cell (0, 1) for the maturity date, then read each data
    row (columns: Dia, Taxa Compra Manhã, Taxa Venda Manhã, PU Compra Manhã,
    PU Venda Manhã, PU Base Manhã) into a PontoTesouro. Never raise on a single
    malformed row — skip it, log it, and keep processing the rest of the sheet.
    """
    raise NotImplementedError
