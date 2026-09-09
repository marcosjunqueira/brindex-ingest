"""CLI entrypoint. Meant to be invoked daily by cron/systemd timer — see
`.specs/New/SPEC_INGESTAO.md` §5 for the (still open) deployment question.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from brindex_ingest.db import connect


def main() -> None:
    parser = argparse.ArgumentParser(prog="brindex-ingest")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("brindex.sqlite"),
        help="Path to the SQLite database file (shared with brindex-api).",
    )
    parser.add_argument(
        "--fonte",
        choices=["tesouro-direto", "ptax", "cdi", "todas"],
        default="todas",
        help="Which source to ingest. Each source fails independently.",
    )
    args = parser.parse_args()

    connect(args.db)
    raise NotImplementedError("wire up sources.tesouro / sources.ptax / sources.cdi here")


if __name__ == "__main__":
    main()
