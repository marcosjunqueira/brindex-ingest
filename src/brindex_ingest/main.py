"""CLI entrypoint. Meant to be invoked daily by cron/systemd timer — see
`.specs/New/SPEC_INGESTION.md` §5 for the (still open) deployment question.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from brindex_ingest.db import PointRow, connect, upsert_points, upsert_series
from brindex_ingest.sources import cdi, ptax, treasury

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ingest_treasury(conn) -> None:
    year = datetime.now(timezone.utc).year
    points = treasury.download_and_normalize(year)
    now = _now_iso()
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
            name=f"Tesouro Direto {point.series} {point.maturity} ({point.side})",
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
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD) for PTAX/CDI ingestion. Defaults to 30 days before today; "
        "pass an earlier date (e.g. 2020-01-01) to backfill on a first run. Ignored by "
        "treasury-direct, which always ingests the current calendar year's full XLS history.",
    )
    args = parser.parse_args()

    today = datetime.now(timezone.utc).date()
    since = args.since or (today - timedelta(days=30)).isoformat()
    until = today.isoformat()

    conn = connect(args.db)

    sources = ["treasury-direct", "ptax", "cdi"] if args.source == "all" else [args.source]

    for source in sources:
        try:
            if source == "treasury-direct":
                _ingest_treasury(conn)
            elif source == "ptax":
                _ingest_ptax(conn, since, until)
            elif source == "cdi":
                _ingest_cdi(conn, since, until)
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("ingestion failed for source %r; continuing with other sources", source)


if __name__ == "__main__":
    main()
