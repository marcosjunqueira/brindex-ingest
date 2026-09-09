"""PTAX (USD reference rate) source: BCB Olinda OData API.

Same endpoint family already used in production by cornerstone-app
(`cornerstone-app/src/storage/bcb.ts`, `CotacaoDolarPeriodo`), reused here
server-side instead of client-side.
"""

from __future__ import annotations

CODIGO_COMPRA = "PTAX:USD:COMPRA"
CODIGO_VENDA = "PTAX:USD:VENDA"


def baixar_e_normalizar(data_inicial: str, data_final: str):
    """TODO: implement. GET the Olinda PTAX OData endpoint for the date range,
    emit one point per day per (compra, venda) pair. Missing/holiday days simply
    produce no row for that date — never a zero or an interpolated value.
    """
    raise NotImplementedError
