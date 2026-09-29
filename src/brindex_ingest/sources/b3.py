"""B3 source: official COTAHIST historical quotes file (daily closes of every B3-listed
instrument — stocks, FIIs, ETFs, BDRs, units — since 1986).

One annual ZIP per year (`COTAHIST_A<YYYY>.ZIP`), holding a single fixed-width latin-1
TXT file, 245 characters per record, layout published by B3 as `SeriesHistoricas_Layout.pdf`
(see SPEC_INGESTION.md §2.2). Only quote records (`TIPREG` `01`) in the spot market
(`TPMERC` `010`, "VISTA") are kept — options, forwards and the odd-lot market
(`020`, "FRACIONARIO", tickers ending in `F`) are dropped.

Prices are integers with two implied decimals, so they are converted with `Decimal`
integer arithmetic only — no `float` ever enters this pipeline. Prices are raw (not
adjusted for dividends or splits), exactly as the official file records them.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Iterator

import requests

logger = logging.getLogger(__name__)

DOMAIN = "b3"

_ANNUAL_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"

_SPOT_MARKET = "010"


@dataclass(frozen=True)
class B3Point:
    ticker: str  # CODNEG, e.g. "PETR4"
    date: str  # ISO date, YYYY-MM-DD
    name: str  # NOMRES + ESPECI, e.g. "PETROBRAS PN"
    bdi_code: str  # CODBDI, e.g. "02" (standard lot), "12" (FII)
    isin: str  # CODISI
    open: str | None
    high: str | None
    low: str | None
    close: str | None
    volume: str | None  # VOLTOT, traded amount in BRL
    trades: str | None  # TOTNEG, number of trades


def canonical_code(ticker: str) -> str:
    return f"{DOMAIN.upper()}:{ticker}"


def _price(field: str, quote_factor: int) -> str | None:
    """`field` is an integer with 2 implied decimals; divide by FATCOT (a power of ten,
    seen from 1 up to 1000000) so the stored value is always the price of one unit. A non-numeric field becomes `None`."""
    try:
        cents = int(field)
    except ValueError:
        return None
    return format(Decimal(cents).scaleb(-2) / quote_factor, "f")


def _int(field: str) -> str | None:
    try:
        return str(int(field))
    except ValueError:
        return None


def parse_lines(lines: Iterable[str]) -> Iterator[B3Point]:
    """Yield one point per spot-market quote record. A malformed record is logged and
    skipped rather than aborting the whole file."""
    for line in lines:
        if line[0:2] != "01" or line[24:27] != _SPOT_MARKET:
            continue
        raw_date, raw_factor = line[2:10], line[210:217]
        if not raw_date.isdigit() or not raw_factor.isdigit() or int(raw_factor) == 0:
            logger.warning("b3: skipping malformed record: %r", line)
            continue
        date = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        quote_factor = int(raw_factor)
        yield B3Point(
            ticker=line[12:24].strip(),
            date=date,
            name=" ".join(f"{line[27:39].strip()} {line[39:49].strip()}".split()),
            bdi_code=line[10:12],
            isin=line[230:242].strip(),
            open=_price(line[56:69], quote_factor),
            high=_price(line[69:82], quote_factor),
            low=_price(line[82:95], quote_factor),
            close=_price(line[108:121], quote_factor),
            volume=_price(line[170:188], 1),
            trades=_int(line[147:152]),
        )


def parse_zip(content: bytes) -> Iterator[B3Point]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        (member,) = archive.namelist()
        with archive.open(member) as raw:
            yield from parse_lines(io.TextIOWrapper(raw, encoding="latin-1"))


def download(year: int, session: requests.Session | None = None) -> bytes:
    http = session or requests
    response = http.get(_ANNUAL_URL.format(year=year), timeout=300)
    response.raise_for_status()
    return response.content


def download_and_normalize(year: int, session: requests.Session | None = None) -> list[B3Point]:
    return list(parse_zip(download(year, session)))
