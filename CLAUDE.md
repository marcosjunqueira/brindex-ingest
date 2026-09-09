# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A standalone daily ingestion CLI (not a server) that downloads three official Brazilian market data
sources — Tesouro Direto, PTAX, CDI — normalizes each into a common time-series shape, and upserts
into a local SQLite database. That database is read by the sibling repo `brindex-api`. The full
design spec lives at [.specs/New/SPEC_INGESTION.md](.specs/New/SPEC_INGESTION.md) — read it before
implementing any source parser or changing the schema; it documents verified, non-obvious facts
about each source (e.g. the Tesouro XLS files are legacy BIFF format, not `.xlsx`; the maturity date
must be read from cell `(0, 1)`, not parsed from the sheet name).

**Status:** early scaffold — schema and CLI skeleton exist; all three source parsers
(`sources/treasury.py`, `sources/ptax.py`, `sources/cdi.py`) and the CLI's ingestion wiring are
`raise NotImplementedError` stubs.

**Naming:** all code, schema, and CLI identifiers are English, including domain terms (e.g.
`--source treasury-direct`, table `points`, column `series_code`) — only literal source-data values
(XLS header strings the Brazilian sources publish, CDN URL path segments) stay in Portuguese, since
those are external data, not project vocabulary — quote them verbatim and add a short English gloss
in parentheses next to the first mention (e.g. `"PU Base Manhã"` (morning base unit price)).
`brindex-api` has not yet been updated to match
these renames (`points`/`series` columns, `PTAX:USD:BUY`/`SELL` codes, `treasury-direct` domain
value) — anything reading/writing the shared database from that repo needs the same rename applied
first.

## Commands

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                    # full test suite
.venv/bin/pytest tests/test_db.py::test_connect_creates_schema  # single test
.venv/bin/brindex-ingest --db brindex.sqlite --source treasury-direct
```

`--source` accepts `treasury-direct`, `ptax`, `cdi`, or `all` (default). There is no lint/format
tooling configured yet.

## Architecture

- `src/brindex_ingest/db.py` — the single source of truth for the SQLite schema (`series`, `points`
  tables) and the `connect()` helper. This schema is duplicated by hand in `brindex-api` — any schema
  change here must be mirrored there manually (no shared migration tool exists yet, by design, until
  the schema has changed at least once in practice).
- `src/brindex_ingest/main.py` — CLI entrypoint (`brindex-ingest` console script). Each source must
  fail independently: a Tesouro Direto CDN outage must never block PTAX/CDI from updating in the same
  run.
- `src/brindex_ingest/sources/{treasury,ptax,cdi}.py` — one module per source, each exposing a
  `download_and_normalize(...)` function that downloads and returns normalized points. No shared base
  class/interface — sources are independent by design (see spec's non-goals).

### Data model

Two tables: `series` (one row per identifiable time series, keyed by `code`) and `points` (one row
per `(series_code, date)`, upserted — never delete-then-insert, since that would create a window
with no row that a concurrent `brindex-api` reader could observe).

Identity scheme, `<DOMAIN>:<IDENTIFIER>`:
- Tesouro Direto: `TD:<SERIES>:<YYYY-MM-DD>`, e.g. `TD:LFT:2026-03-01` — `<SERIES>` ∈
  `{LFT, LTN, NTNB-PRINCIPAL}`. This scheme is deliberately kept consistent with a related spec in
  the `portfolio-rebalancer` repo (`SPEC_TESOURO_DIRETO_CATALOGO_OFICIAL.md`); the two projects are
  fully decoupled otherwise.
- PTAX: `PTAX:USD:BUY` / `PTAX:USD:SELL`.
- CDI: `CDI:SGS:4391` (the BCB SGS series number, already a stable public identifier).

**Money/decimal discipline (non-negotiable, per spec §6):** every price/rate value is stored as SQL
`TEXT`, never `REAL` — floats must never enter the historical record. A missing or non-numeric
source value must become SQL `NULL`, never `NaN`, an empty string, or a sentinel. This must be
enforced at the parser boundary (`sources/*.py`) before a row ever reaches `db.py`.

**Idempotency:** `(series_code, date)` is the primary key of `points`. Re-running ingestion for a
date already present must overwrite via `INSERT ... ON CONFLICT DO UPDATE`, not error or duplicate —
this matters concretely for Tesouro Direto, whose "PU Base Manhã" (morning base unit price) can be
revised later the same day.

### Testing conventions

Source parsers must be tested against fixture files (`tests/fixtures/`) — never live network calls.
Tesouro Direto fixtures are the real `.xls` files downloaded during spec design (~100–160 KB each,
committed on purpose). Required test coverage per spec §7 beyond basic parsing:
- Idempotency: ingesting the same source/date range twice leaves `points` with the same row count as
  once, and updates `value` if the fixture's second run carries a corrected value.
- Money boundary: a fixture row with an empty/malformed price cell must produce a `NULL` `value`,
  never a crash or a silently wrong number.
