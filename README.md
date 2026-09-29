# brindex-ingest

Daily ingestion and parsing of official Brazilian market series (Tesouro Direto, PTAX, CDI, B3 daily closes) into a
historical time-series SQLite database, read by [`brindex-api`](https://github.com/marcosjunqueira/brindex-api).

## Status

Schema, CLI, and all source parsers (`sources/treasury.py`, `sources/ptax.py`,
`sources/cdi.py`, `sources/b3.py`) are implemented and tested against fixtures. See [`.specs/`](.specs/)
for the design.

## Sources

| Domain | Source | Format |
|---|---|---|
| Tesouro Direto | `tesourotransparente.gov.br` open-data CSV | CSV |
| PTAX | BCB Olinda OData | JSON |
| CDI | BCB SGS series 4391 | JSON |
| B3 (stocks, FIIs, ETFs, BDRs) | B3 COTAHIST annual file | ZIP of fixed-width TXT |

## Running

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/brindex-ingest --db brindex.sqlite --source all
```

`--source` accepts `treasury-direct`, `ptax`, `cdi`, `b3`, or `all` (default) — each source
fails independently, so an outage in one never blocks the others in the same run.

`--since YYYY-MM-DD` sets the backfill start date for PTAX/CDI (default: 30 days before
today); pass an earlier date (e.g. `--since 2020-01-01`) on a first run to backfill
further back. Ignored by `treasury-direct` and `b3`, which use `--year`/`--since-year` instead.

`--year YYYY` ingests `treasury-direct` rows dated in a single calendar year only (the
source is one CSV covering full history since 2002 — this filters which rows get
written, not which are downloaded); defaults to the current year. `--since-year YYYY`
ingests every year from `YYYY` through the current one, inclusive — use it to backfill
years before the current one, e.g. `--since-year 2020`. For `b3` each year is one
COTAHIST download. The two are mutually exclusive
and both are ignored by `ptax`/`cdi`.

## Docker image and releases

Each `vX.Y.Z` tag on `main` publishes `ghcr.io/marcosjunqueira/brindex-ingest:X.Y.Z` (plus `X.Y`, `X`
and `latest`) and a GitHub Release. The image is a one-shot job: it runs one ingestion into
`/data/brindex.sqlite` and exits with the same code as the CLI; arguments are passed through. In
production it runs as the `ingest` service of brindex-api's
[`deploy/docker-compose.yml`](https://github.com/marcosjunqueira/brindex-api/blob/main/deploy/docker-compose.yml),
scheduled by host cron (`docker compose run --rm ingest`); see brindex-api's
[`docs/GO_LIVE.md`](https://github.com/marcosjunqueira/brindex-api/blob/main/docs/GO_LIVE.md) §3.

```bash
docker build -t brindex-ingest .
docker run --rm -v "$PWD/data:/data" --user "$(id -u):$(id -g)" brindex-ingest --source ptax
```

## License

MIT — see [LICENSE](LICENSE).
