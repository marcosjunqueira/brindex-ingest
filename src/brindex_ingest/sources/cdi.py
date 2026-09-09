"""CDI source: BCB SGS API, series 4391.

Same endpoint already used in production by cornerstone-app
(`cornerstone-app/src/storage/bcb.ts`), reused here server-side.
"""

from __future__ import annotations

CODE = "CDI:SGS:4391"


def download_and_normalize(start_date: str, end_date: str):
    """TODO: implement. GET https://api.bcb.gov.br/dados/serie/bcdata.sgs.4391/dados
    for the date range, emit one point per business day.
    """
    raise NotImplementedError
