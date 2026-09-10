"""CLI entrypoint. Meant to be invoked daily by cron/systemd timer — see
`.specs/New/SPEC_INGESTION.md` §5 for the (still open) deployment question.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from brindex_ingest.db import PointRow, connect, upsert_points, upsert_series
from brindex_ingest.sources import cdi, ptax, treasury

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ingest_treasury(conn, years: list[int]) -> None:
    """Filters the downloaded points down to those dated (`Data Base`) in one of
    `years` — the CSV source (SPEC_INGESTION.md §2.1) is a single file covering full
    history since 2002, so unlike the superseded per-year CDN `.xls` files, filtering
    happens in memory after one download, not as separate per-year requests.
    """
    now = _now_iso()
    points = treasury.download_and_normalize()
    wanted_years = set(years)
    points = [p for p in points if int(p.date[:4]) in wanted_years]

    seen_codes: set[str] = set()
    for point in points:
        code = treasury.canonical_code(point.series, point.maturity, point.side)
        if code in seen_codes:
            continue
        seen_codes.add(code)
        upsert_series(
            conn,
            code=code,
            domain="treasury-direct",
            name=treasury.display_name(point.series, point.maturity, point.side),
            metadata={"maturity": point.maturity, "series": point.series, "side": point.side},
            created_at=now,
        )
    upsert_points(
        conn,
        (
            PointRow(
                series_code=treasury.canonical_code(point.series, point.maturity, point.side),
                date=point.date,
                value=point.price,
                extra_values=json.dumps({"rate": point.rate, "base_price": point.base_price}),
                source_updated_at=now,
            )
            for point in points
        ),
    )


def _ingest_ptax(conn, since: str, until: str) -> None:
    points = ptax.download_and_normalize(since, until)
    now = _now_iso()
    upsert_series(
        conn,
        code=ptax.BUY_CODE,
        domain="ptax",
        name="PTAX USD Buy",
        metadata={"currency": "USD"},
        created_at=now,
    )
    upsert_series(
        conn,
        code=ptax.SELL_CODE,
        domain="ptax",
        name="PTAX USD Sell",
        metadata={"currency": "USD"},
        created_at=now,
    )
    upsert_points(
        conn,
        (
            PointRow(
                series_code=point.code,
                date=point.date,
                value=point.value,
                extra_values=None,
                source_updated_at=now,
            )
            for point in points
        ),
    )


def _ingest_cdi(conn, since: str, until: str) -> None:
    points = cdi.download_and_normalize(since, until)
    now = _now_iso()
    upsert_series(
        conn,
        code=cdi.CODE,
        domain="cdi",
        name="CDI",
        metadata={"sgs_series": 4391},
        created_at=now,
    )
    upsert_points(
        conn,
        (
            PointRow(
                series_code=cdi.CODE,
                date=point.date,
                value=point.value,
                extra_values=None,
                source_updated_at=now,
            )
            for point in points
        ),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(prog="brindex-ingest")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("BRINDEX_DB_PATH", "brindex.sqlite")),
        help="Path to the SQLite database file (shared with brindex-api). Defaults to the "
        "BRINDEX_DB_PATH environment variable if set (the same variable brindex-api reads), "
        "else ./brindex.sqlite.",
    )
    parser.add_argument(
        "--source",
        choices=["treasury-direct", "ptax", "cdi", "all"],
        default="all",
        help="Which source to ingest. Each source fails independently.",
    )
    parser.add_argument(
        "--since",
        type=_iso_date,
        default=None,
        help="Start date (YYYY-MM-DD) for PTAX/CDI ingestion. Defaults to 30 days before today; "
        "pass an earlier date (e.g. 2020-01-01) to backfill on a first run. Ignored by "
        "treasury-direct, which uses --year/--since-year instead.",
    )
    year_group = parser.add_mutually_exclusive_group()
    year_group.add_argument(
        "--year",
        type=int,
        default=None,
        help="Ingest treasury-direct rows dated (Data Base) in this single calendar year "
        "only. The source is now one CSV covering full history since 2002 (a single "
        "download regardless of this flag) — this only filters which rows get written. "
        "Defaults to the current year. Mutually exclusive with --since-year. Ignored by "
        "ptax/cdi.",
    )
    year_group.add_argument(
        "--since-year",
        type=int,
        default=None,
        help="Ingest treasury-direct rows dated (Data Base) from this calendar year "
        "through the current year, inclusive — use to backfill years before the current "
        "one, e.g. --since-year 2020 (or an early year like 2002 for the full history). "
        "Mutually exclusive with --year. Ignored by ptax/cdi.",
    )
    args = parser.parse_args()

    today = datetime.now(timezone.utc).date()
    since = args.since if args.since is not None else (today - timedelta(days=30)).isoformat()
    until = today.isoformat()
    if args.year is not None:
        years = [args.year]
    elif args.since_year is not None:
        years = list(range(args.since_year, today.year + 1))
    else:
        years = [today.year]

    conn = connect(args.db)

    sources = ["treasury-direct", "ptax", "cdi"] if args.source == "all" else [args.source]

    failed_sources: list[str] = []
    for source in sources:
        try:
            if source == "treasury-direct":
                _ingest_treasury(conn, years)
            elif source == "ptax":
                _ingest_ptax(conn, since, until)
            elif source == "cdi":
                _ingest_cdi(conn, since, until)
            conn.commit()
        except Exception:
            conn.rollback()
            failed_sources.append(source)
            logger.exception("ingestion failed for source %r; continuing with other sources", source)

    if failed_sources:
        logger.error("ingestion run failed for source(s): %s", ", ".join(failed_sources))
        sys.exit(1)


def _iso_date(value: str) -> str:
    """Validate `--since` eagerly at the argparse layer, so a typo'd date fails loudly
    instead of being caught and logged as an ordinary per-source ingestion failure."""
    datetime.strptime(value, "%Y-%m-%d")
    return value


if __name__ == "__main__":
    main()
