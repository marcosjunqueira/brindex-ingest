# brindex-ingest

Daily ingestion and parsing of official Brazilian market series (Tesouro Direto, PTAX, CDI) into a
historical time-series SQLite database, read by [`brindex-api`](https://github.com/marcosjunqueira/brindex-api).

## Status

Schema, CLI, and all three source parsers (`sources/treasury.py`, `sources/ptax.py`,
`sources/cdi.py`) are implemented and tested against fixtures. See [`.specs/`](.specs/)
for the design.

## Sources

| Domain | Source | Format |
|---|---|---|
| Tesouro Direto | `cdn.tesouro.gov.br/.../{type}_{year}.xls` | legacy XLS (BIFF) |
| PTAX | BCB Olinda OData | JSON |
| CDI | BCB SGS series 4391 | JSON |

## Running

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/brindex-ingest --db brindex.sqlite --source all
```

`--source` accepts `treasury-direct`, `ptax`, `cdi`, or `all` (default) — each source
fails independently, so an outage in one never blocks the others in the same run.

`--since YYYY-MM-DD` sets the backfill start date for PTAX/CDI (default: 30 days before
today); pass an earlier date (e.g. `--since 2020-01-01`) on a first run to backfill
further back. Ignored by `treasury-direct`, which uses `--year`/`--since-year` instead.

`--year YYYY` ingests `treasury-direct` for a single calendar year (each Tesouro Direto
XLS is published per-year by the CDN); defaults to the current year. `--since-year YYYY`
ingests every year from `YYYY` through the current one, inclusive — use it to backfill
years before the current one, e.g. `--since-year 2020`. The two are mutually exclusive
and both are ignored by `ptax`/`cdi`.

## License

MIT — see [LICENSE](LICENSE).
