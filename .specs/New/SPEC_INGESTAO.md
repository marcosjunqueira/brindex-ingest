# Specification — Daily ingestion of Tesouro Direto, PTAX and CDI into BRIndex

**Status:** New — scaffold exists (schema, CLI skeleton, package layout), no source parser
implemented yet (`sources/*.py` all `raise NotImplementedError`)
**Date:** 2026-09-09
**Repo:** `brindex-ingest`
**Related:** `brindex-api` (reads the database this writes to — `SPEC_READ_API.md` there mirrors the
schema below); `portfolio-rebalancer/.specs/New/SPEC_TESOURO_DIRETO_CATALOGO_OFICIAL.md` (the
cornerstone-app fix this project's identity scheme was designed to stay consistent with, though the
two are fully decoupled — neither blocks the other).

---

## 1. Purpose

A standalone process (not a long-lived server) that, once a day, downloads three official Brazilian
public data sources, normalizes each into a common time-series shape, and upserts into a local
SQLite database. Solves, for personal use first, the problem that `cornerstone-app` currently either
hardcodes a snapshot (Tesouro Direto — see the related spec) or re-fetches PTAX/CDI live from the
browser on every use (`cornerstone-app/src/storage/bcb.ts`) with no persisted history.

## 2. Sources

| Domain | Endpoint | Format | Notes |
|---|---|---|---|
| Tesouro Direto | `https://cdn.tesouro.gov.br/sistemas-internos/apex/producao/sistemas/sistd/{ano}/{tipo}_{ano}.xls` | legacy BIFF `.xls` (confirmed 2026-09-09 via `file`, NOT `.xlsx`) | One file per `tipo` (`LFT`, `LTN`, `NTN-B_Principal`), one sheet per maturity, full-year daily history per sheet |
| PTAX | BCB Olinda OData, `CotacaoDolarPeriodo` | JSON | Same endpoint already used client-side by `cornerstone-app/src/storage/bcb.ts:100-104` |
| CDI | BCB SGS, `bcdata.sgs.4391` | JSON | Same endpoint already used by `cornerstone-app/src/storage/bcb.ts:137-139` |

Each source is ingested and can fail **independently** — a Tesouro Direto CDN outage must not
prevent PTAX/CDI from updating, and vice versa. `main.py --fonte` already models this (one source at
a time, or `todas`).

### 2.1 Tesouro Direto XLS structure (verified, not assumed)

Confirmed by downloading and opening the three current files with `xlrd`:
- Sheet names encode série + vencimento: `"LFT 010326"` = LFT maturing 2026-03-01.
- Cell `(0, 1)` of every sheet holds the maturity date explicitly (`"Vencimento"` / `"01/03/2026"`)
  — **use this cell as the source of truth for the date**, not a parse of the sheet name; they agree
  today but the cell is the more direct signal.
- Row 1 is the header: `Dia, Taxa Compra Manhã, Taxa Venda Manhã, PU Compra Manhã, PU Venda Manhã,
  PU Base Manhã`. Data starts at row 2.
- Each sheet holds the **full calendar-year daily history** for that maturity, not just the current
  day — including maturities that already expired within the year (e.g. `LFT_2026.xls` still
  contains `LFT 010326`, which matured 2026-03-01, with data through its last trading day). This is
  what makes a daily ingestion meaningful from day one: even a single run recovers a whole year of
  backfill, not just "today".

## 3. Data model

```sql
CREATE TABLE series (
  codigo        TEXT PRIMARY KEY,   -- 'TD:LFT:2026-03-01' | 'PTAX:USD:VENDA' | 'CDI:SGS:4391'
  dominio       TEXT NOT NULL,      -- 'tesouro-direto' | 'ptax' | 'cdi'
  nome          TEXT NOT NULL,
  metadados     TEXT NOT NULL,      -- opaque JSON, domain-specific (vencimento/moeda/etc.)
  criado_em     TEXT NOT NULL
);

CREATE TABLE pontos (
  serie_codigo  TEXT NOT NULL REFERENCES series(codigo),
  data          TEXT NOT NULL,      -- YYYY-MM-DD
  valor         TEXT NOT NULL,      -- decimal as STRING, never float — see §6
  valores_extra TEXT,               -- optional JSON: e.g. Tesouro's compra/venda alongside base
  fonte_atualizado_em TEXT NOT NULL,
  PRIMARY KEY (serie_codigo, data)
);
```

Implemented in `src/brindex_ingest/db.py`, tested (`tests/test_db.py::test_connect_creates_schema`,
passing). `brindex-api` reads this same file — the schema is currently synchronized **by hand**
between the two repos; formalizing that (a shared schema-version file, a migration tool) is
explicitly deferred until the schema has changed at least once in practice.

### 3.1 Identity scheme

`<DOMINIO>:<IDENTIFICADOR>`:
- Tesouro Direto: `TD:<SERIE>:<AAAA-MM-DD>` — `<SERIE>` ∈ `{LFT, LTN, NTNB-PRINCIPAL}`, reusing the
  exact scheme designed for cornerstone-app's own static catalog fix (kept consistent on purpose,
  not by coincidence — see the related spec).
- PTAX: `PTAX:USD:COMPRA` / `PTAX:USD:VENDA`.
- CDI: `CDI:SGS:4391` (the BCB SGS series number is already a stable, public identifier).

`codigo_canonico()` for Tesouro Direto is implemented in `sources/tesouro.py`; PTAX/CDI's constants
are module-level in their own files (no function needed — they're each a fixed pair/singleton, not a
family parameterized by maturity).

## 4. Idempotency and upserts

`(serie_codigo, data)` is the primary key of `pontos` — re-running ingestion for a date already
present must **overwrite**, not error or duplicate. This matters concretely for Tesouro Direto: the
"PU Base Manhã" published early in the day can be revised later, so a same-day re-run should pick up
the correction. Not yet implemented (the `main.py` CLI stops at `connect()` and raises
`NotImplementedError`) — when it is, the upsert must be a real `INSERT ... ON CONFLICT DO UPDATE`,
not a delete-then-insert (which would create a window with no row, however brief, that a concurrent
`brindex-api` read could observe).

## 5. Scheduling and deployment (open question, not resolved here)

This process needs to run daily. Candidates, not decided:
- `cron` or a `systemd timer` on a host the user controls (there's existing precedent: an n8n
  instance already runs personal automations at `n8n.sitetune.com.br`, though that specific
  workflow was abandoned as a *data source* — see the related cornerstone spec's history — the host
  itself is still a candidate for *running this ingestion job*, which is a different question).
- A small VPS or a home device (Raspberry Pi) dedicated to this and possibly other personal
  services.

Whichever is chosen, the job is a single CLI invocation (`brindex-ingest --fonte todas`) — the
scheduling mechanism is infrastructure, not application code, and doesn't change anything in this
repo.

## 6. Money/decimal discipline

Every price/rate value ends up in SQLite as `TEXT`, never `REAL` — this is deliberate, to prevent
float round-off from ever entering the historical record. A missing or non-numeric cell/field from a
source must become SQL `NULL`, never a `NaN`, an empty string, or a sentinel value. This must be
enforced at the parser boundary (`sources/*.py`), before a row ever reaches `db.py`.

## 7. Testing

- `tests/test_db.py` — schema creation, implemented and passing.
- Each source parser needs unit tests against **fixture files**, never live network calls in CI:
  - Tesouro Direto: the three `.xls` files downloaded during this spec's design session are the
    first candidate fixtures (not yet committed to `tests/fixtures/` — do so before implementing
    `sources/tesouro.py`, keeping file size in mind: ~100–160 KB each, acceptable to commit).
  - PTAX/CDI: a captured JSON response per endpoint, small and easy to fixture.
- Idempotency test: running ingestion for the same source and date range twice must leave `pontos`
  with exactly the same row count as running it once (no duplicates), and update `valor` if the
  fixture's second run carries a different (corrected) value.
- Money-boundary test (per §6): a fixture row with an empty/malformed price cell must produce a
  `NULL` `valor` in the database, never a crash or a silently wrong number.

## 8. Non-goals for v1

- No authentication/authorization anywhere in this repo — it only ever writes to a local file.
- No retry/backoff policy beyond "fail this source, log it, let the next scheduled run try again" —
  a more sophisticated retry strategy is deferred until an actual outage pattern is observed.
- No multi-instance/concurrency handling — this is assumed to run as a single scheduled job, not
  multiple overlapping instances.
