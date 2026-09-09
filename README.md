# brindex-ingest

Daily ingestion and parsing of official Brazilian market series (Tesouro Direto, PTAX, CDI) into a
historical time-series SQLite database, read by [`brindex-api`](https://github.com/marcosjunqueira/brindex-api).

## Status

Early scaffold. Schema and CLI wired up; the three source parsers (`sources/treasury.py`,
`sources/ptax.py`, `sources/cdi.py`) are stubs (`raise NotImplementedError`). See
[`.specs/`](.specs/) for the design.

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
.venv/bin/brindex-ingest --db brindex.sqlite --source treasury-direct
```

## License

MIT — see [LICENSE](LICENSE).
