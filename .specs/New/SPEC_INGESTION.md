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
| Tesouro Direto | `https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv` | CSV, `;`-delimited, `latin-1`, decimal comma (confirmed 2026-09-09) | **Source changed 2026-09-09 — see §2.1a.** One file, all title types, full history since January 2002 (~176k rows) |
| PTAX | BCB Olinda OData, `CotacaoDolarPeriodo` | JSON | Same endpoint already used client-side by `cornerstone-app/src/storage/bcb.ts:100-104` |
| CDI | BCB SGS, `bcdata.sgs.4391` | JSON | Same endpoint already used by `cornerstone-app/src/storage/bcb.ts:137-139`. Confirmed live 2026-09-09: series 4391 is **monthly**, one entry per calendar month dated the 1st (`{"data": "01/09/2026", "valor": "0.26"}`) — not daily, despite "CDI" evoking a daily rate. |

Each source is ingested and can fail **independently** — a Tesouro Direto CDN outage must not
prevent PTAX/CDI from updating, and vice versa. `main.py --source` already models this (one source at
a time, or `all`).

### 2.1 Tesouro Direto CSV structure (verified, not assumed)

**Source changed 2026-09-09.** The CDN `.xls` files (`cdn.tesouro.gov.br/.../sistd/{year}/{type}_{year}.xls`,
documented in §2.1's original text — kept below in §2.1a for provenance) turned out to be **stale in
production**: discovered 2026-09-09 while investigating a user report that several titles (including
long-dated ones like Tesouro IPCA+ 2035/2040/2050, nowhere near maturity) showed no quotes past
2026-08-21. Re-downloading `NTN-B_2026.xls` live confirmed **all ten sheets** in that file — every
maturity from 2026 through 2060 — stop at the same date, 2026-08-21, ~3 weeks before the check date.
This is a whole-file staleness on the CDN, not a per-title maturity artifact.

Two alternatives were evaluated:
- `tesourodireto.com.br`'s own "Rendimento dos Títulos" page turned out to be backed by a live JSON
  API (`/o/c/rentabilidades/`, a Liferay Headless Delivery custom object) returning same-day data —
  but that host sits behind a Cloudflare managed challenge; a plain HTTP client gets a "Just a
  moment..." challenge page instead of JSON. Only a real browser session that already solved the JS
  challenge could read it. **Rejected**: would require a headless-browser dependency (e.g.
  Playwright) just to pass an anti-bot check, adding heavy infra and fragility (breaks silently if
  Cloudflare's challenge changes) for an undocumented, unofficial endpoint.
- **Chosen:** the Tesouro Nacional open-data portal, `tesourotransparente.gov.br` (CKAN-based,
  the same software as `dados.gov.br`) — a completely different system from `tesourodireto.com.br`
  aimed at programmatic/public consumption, with no anti-bot protection. Its dataset
  `taxas-dos-titulos-ofertados-pelo-tesouro-direto` ("Taxas dos Títulos Ofertados pelo Tesouro
  Direto") publishes exactly the same underlying numbers — verified by cross-checking overlapping
  rows against the stale `.xls` (`NTN-B 150832`/`Tesouro IPCA+ com Juros Semestrais` vencimento
  `15/08/2032`, dates 19–21/08/2026: PU values matched to the cent) — but the resource's
  `last_modified` was `2026-09-09T10:21:10`, and its most recent row for that same title was dated
  `08/09/2026` (the prior business day), i.e. genuinely current, not stuck. Dataset metadata:
  `https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=taxas-dos-titulos-ofertados-pelo-tesouro-direto`.
  License: ODbL (Open Data Commons) — official open data, no auth required.

Confirmed by downloading and parsing the live CSV on 2026-09-09:
- One file, one header row, columns (source's literal Portuguese headers, `;`-delimited,
  `latin-1`-encoded, decimal comma): `Tipo Titulo` (title type), `Data Vencimento` (maturity date,
  `DD/MM/YYYY`), `Data Base` (as-of date, `DD/MM/YYYY`), `Taxa Compra Manha` (morning buy rate),
  `Taxa Venda Manha` (morning sell rate), `PU Compra Manha` (morning buy unit price), `PU Venda
  Manha` (morning sell unit price), `PU Base Manha` (morning base unit price) — the same fields the
  old `.xls` had, just reshaped into one flat table instead of one workbook per type/one sheet per
  maturity.
- `Tipo Titulo` is a **retail product name**, not the `<SERIES>` token used in this repo's identity
  scheme — critically, `Tesouro IPCA+` (no coupon; PU carries no accrued coupon value) and `Tesouro
  IPCA+ com Juros Semestrais` (semiannual coupon; materially higher PU for the same maturity, since
  it embeds future coupon payments) are **different instruments that can share the same `Data
  Vencimento`** — conflating them silently would corrupt the series. See §3.1a for the full mapping
  from `Tipo Titulo` strings to `<SERIES>` tokens.
- One row per `(Tipo Titulo, Data Vencimento, Data Base)` — no separate "sheet" concept; a maturity's
  full history is just every row matching its `Data Vencimento`, going back to whenever that title
  started trading (as early as January 2002 for some series).
- Same two-sided pricing as before: `PU Compra Manha` (invest) vs. `PU Venda Manha` (redeem) remain
  genuinely distinct and are still ingested as two points per row — §3.1's `:BUY`/`:SELL` scheme is
  unaffected by the source change.

### 2.1a Tesouro Direto XLS structure (superseded 2026-09-09, kept for provenance)

Confirmed by downloading and opening all five current files with `xlrd`, before the switch to the
CSV source above:
- Sheet names encode series + maturity: `"LFT 010326"` = LFT maturing 2026-03-01.
- Cell `(0, 1)` of every sheet holds the maturity date explicitly (`"Vencimento"` / `"01/03/2026"` —
  "maturity date", the source's literal Portuguese header).
- Row 1 is the header (source's literal Portuguese column names): `Dia` (day), `Taxa Compra Manhã`
  (morning buy rate), `Taxa Venda Manhã` (morning sell rate), `PU Compra Manhã` (morning buy unit
  price), `PU Venda Manhã` (morning sell unit price), `PU Base Manhã` (morning base unit price). Data
  starts at row 2.
- Each sheet held the full calendar-year daily history for that maturity, not just the current day.
- This CDN endpoint is not being removed from the world and may still be worth a fallback source if
  the CSV portal ever goes down, but it is no longer the primary source implemented against — its
  update cadence has been observed unreliable (see §2.1) and it requires a binary XLS parser
  (`xlrd`) instead of a plain CSV reader.

## 3. Data model

```sql
CREATE TABLE series (
  code          TEXT PRIMARY KEY,   -- 'TD:LFT:2026-03-01' | 'PTAX:USD:SELL' | 'CDI:SGS:4391'
  domain        TEXT NOT NULL,      -- 'treasury-direct' | 'ptax' | 'cdi'
  name          TEXT NOT NULL,
  metadata      TEXT NOT NULL,      -- opaque JSON, domain-specific (maturity/currency/etc.)
  created_at    TEXT NOT NULL
);

CREATE TABLE points (
  series_code   TEXT NOT NULL REFERENCES series(code),
  date          TEXT NOT NULL,      -- YYYY-MM-DD
  value         TEXT,               -- decimal as STRING, never float — see §6. NULLable: a
                                     -- missing/malformed source cell becomes SQL NULL, never a
                                     -- crash or a sentinel (§6/§7) — so this column cannot be
                                     -- NOT NULL, even though every point observed against the live
                                     -- sources so far (5192/5192, 2026-09-09) happens to have one.
  extra_values  TEXT,               -- optional JSON: e.g. Treasury's buy/sell alongside base
  source_updated_at TEXT NOT NULL,
  PRIMARY KEY (series_code, date)
);
```

Implemented in `src/brindex_ingest/db.py`, tested (`tests/test_db.py::test_connect_creates_schema`,
passing). `brindex-api` reads this same file — the schema is currently synchronized **by hand**
between the two repos; formalizing that (a shared schema-version file, a migration tool) is
explicitly deferred until the schema has changed at least once in practice.

**Correction (2026-09-09, found via cross-session review while `brindex-api` was validating its
read path against a real ingested database):** `points.value` was originally declared `TEXT NOT
NULL` here and in `db.py` — a direct contradiction of §6/§7's requirement that a missing/malformed
value become `NULL`. `upsert_points` with a `None` value raised `sqlite3.IntegrityError` before
this was caught; the existing money-boundary tests only exercised the parsing functions in
isolation and never round-tripped a `None` value through `db.upsert_points`, so the bug shipped
silently (it also never triggered against real Tesouro/PTAX/CDI data, since no live row observed
so far actually had a malformed cell). Fixed to `value TEXT` (nullable) in both this schema and
`db.py`. Any database created before this fix must be recreated (`CREATE TABLE IF NOT EXISTS`
does not retroactively relax an existing table's `NOT NULL`) — there is no migration tool yet, per
§0/`CLAUDE.md`.

### 3.1 Identity scheme

`<DOMAIN>:<IDENTIFIER>`:
- Tesouro Direto: `TD:<SERIES>:<YYYY-MM-DD>:<SIDE>` — `<SERIES>` ∈ `{LFT, LTN, NTNB-PRINCIPAL, NTNB, NTNF}`,
  `<YYYY-MM-DD>` is the maturity date, `<SIDE>` ∈ `{BUY, SELL}` (e.g. `TD:LFT:2026-03-01:BUY`).

  **Breaking change vs. earlier drafts, decided during implementation planning (2026-09-09):** the
  original scheme was `TD:<SERIES>:<YYYY-MM-DD>` with no side suffix, one series per maturity,
  deliberately kept identical to the scheme designed for `portfolio-rebalancer`'s own Tesouro Direto
  catalog fix (`SPEC_TESOURO_DIRETO_CATALOGO_OFICIAL.md`) — kept consistent on purpose, not by
  coincidence. That single-series-per-maturity shape forced picking either the invest price (`PU
  Compra Manhã`) or the redeem price (`PU Venda Manhã`) into the lone `value` column, silently
  discarding the other — so it was replaced with two series per maturity, one per side, matching how
  PTAX already models `BUY`/`SELL`. **This intentionally breaks the naming alignment with
  `portfolio-rebalancer`'s catalog scheme** — the two repos are still "fully decoupled" (per §0/the
  header above; neither blocks the other), but a consumer relying on the old scheme's exact string
  shape must be updated. `brindex-api` has not been updated to match this rename either, same as the
  other pending renames noted in `CLAUDE.md`.
- PTAX: `PTAX:USD:BUY` / `PTAX:USD:SELL` (previously `COMPRA` / `VENDA` — renamed for the
  English-everywhere pass; this is a stored-data breaking change, see note below).
- CDI: `CDI:SGS:4391` (the BCB SGS series number is already a stable, public identifier).

`canonical_code()` for Tesouro Direto is implemented in `sources/treasury.py`; PTAX/CDI's constants
are module-level in their own files (no function needed — they're each a fixed pair/singleton, not a
family parameterized by maturity).

### 3.1a `Tipo Titulo` → `<SERIES>` mapping (added 2026-09-09, with the CSV source switch)

The CSV's `Tipo Titulo` values must be mapped to this repo's `<SERIES>` tokens at the parser boundary
(`sources/treasury.py`) before a row reaches `db.py` — the CSV string is source vocabulary, not
project vocabulary, same rule as elsewhere in this repo (see `CLAUDE.md`/Naming):

| `Tipo Titulo` (source, Portuguese) | `<SERIES>` token |
|---|---|
| `Tesouro Selic` | `LFT` |
| `Tesouro Prefixado` | `LTN` |
| `Tesouro Prefixado com Juros Semestrais` | `NTNF` |
| `Tesouro IPCA+` | `NTNB-PRINCIPAL` |
| `Tesouro IPCA+ com Juros Semestrais` | `NTNB` |

**Open question, not resolved here:** the live CSV also contains three `Tipo Titulo` values with no
corresponding `<SERIES>` token in the current enum (`{LFT, LTN, NTNB-PRINCIPAL, NTNB, NTNF}`) —
`Tesouro Educa+`, `Tesouro Renda+ Aposentadoria Extra`, and `Tesouro IGPM+ com Juros Semestrais`.
These are newer retail products (Educa+/RendA+ didn't exist when the original `<SERIES>` enum was
designed) that were invisible in the old `.xls` feed's five files but are present in this CSV. Until
this is decided, `sources/treasury.py` must skip unmapped `Tipo Titulo` values explicitly (log and
continue, per §2's independent-failure principle) rather than crash or silently mis-map them — adding
`<SERIES>` tokens for them is future scope.

**Breaking change vs. earlier drafts of this spec:** table/column names, the `--fonte` CLI flag, and
the `series.domain` value `tesouro-direto` were originally Portuguese (`pontos`, `codigo`, `dominio`,
`nome`, `metadados`, `criado_em`, `serie_codigo`, `data`, `valor`, `valores_extra`,
`fonte_atualizado_em`). They have been renamed to English throughout this repo (schema, CLI, source
modules). `brindex-api` must apply the same renames before either repo touches a shared database —
this has not yet happened outside this repo.

## 4. Idempotency and upserts

`(series_code, date)` is the primary key of `points` — re-running ingestion for a date already
present must **overwrite**, not error or duplicate. This matters concretely for Tesouro Direto: the
"PU Base Manhã" (morning base unit price) published early in the day can be revised later, so a
same-day re-run should pick up the correction. Not yet implemented (the `main.py` CLI stops at
`connect()` and raises `NotImplementedError`) — when it is, the upsert must be a real
`INSERT ... ON CONFLICT DO UPDATE`, not a delete-then-insert (which would create a window with no
row, however brief, that a concurrent `brindex-api` read could observe).

## 5. Scheduling and deployment (open question, not resolved here)

This process needs to run daily. Candidates, not decided:
- `cron` or a `systemd timer` on a host the user controls (there's existing precedent: an n8n
  instance already runs personal automations at `n8n.sitetune.com.br`, though that specific
  workflow was abandoned as a *data source* — see the related cornerstone spec's history — the host
  itself is still a candidate for *running this ingestion job*, which is a different question).
- A small VPS or a home device (Raspberry Pi) dedicated to this and possibly other personal
  services.

Whichever is chosen, the job is a single CLI invocation (`brindex-ingest --source all`) — the
scheduling mechanism is infrastructure, not application code, and doesn't change anything in this
repo.

### 5.1 Database path convention (aligned with `brindex-api`, 2026-09-09)

`--db` defaults to the `BRINDEX_DB_PATH` environment variable if set, else `./brindex.sqlite` —
`brindex-api`'s `Application.kt` reads the same `BRINDEX_DB_PATH` variable (defaulting to
`brindex.sqlite` there too), so setting it once points both processes at the same file. Confirmed
via cross-session coordination with the `brindex-api` implementation: its local dev/preview
`.claude/launch.json` points at `/tmp/brindex/brindex.sqlite` (not `/opt/brindex` — that directory
is `root:root`, unwritable without `sudo`). Neither repo hardcodes a shared default path; only the
env var name is a shared convention.

## 6. Money/decimal discipline

Every price/rate value ends up in SQLite as `TEXT`, never `REAL` — this is deliberate, to prevent
float round-off from ever entering the historical record. A missing or non-numeric cell/field from a
source must become SQL `NULL`, never a `NaN`, an empty string, or a sentinel value. This must be
enforced at the parser boundary (`sources/*.py`), before a row ever reaches `db.py`.

## 7. Testing

- `tests/test_db.py` — schema creation, implemented and passing.
- Each source parser needs unit tests against **fixture files**, never live network calls in CI:
  - Tesouro Direto: as of the 2026-09-09 source switch (§2.1), the fixture should be a **trimmed
    slice** of `precotaxatesourodireto.csv` (the live file is ~14 MB/176k rows — commit only the rows
    needed to exercise each `<SERIES>` mapping, a maturity boundary, and at least one malformed/empty
    price cell for the money-boundary test below), not the full download. The five `.xls` files
    committed under `tests/fixtures/` for the superseded CDN source (§2.1a) can be removed once the
    CSV parser and its own fixture are in place and passing — not before, to avoid a gap in test
    coverage mid-migration.
  - PTAX/CDI: a captured JSON response per endpoint, small and easy to fixture.
- Idempotency test: running ingestion for the same source and date range twice must leave `points`
  with exactly the same row count as running it once (no duplicates), and update `value` if the
  fixture's second run carries a different (corrected) value.
- Money-boundary test (per §6): a fixture row with an empty/malformed price cell must produce a
  `NULL` `value` in the database, never a crash or a silently wrong number.

## 8. Non-goals for v1

- No authentication/authorization anywhere in this repo — it only ever writes to a local file.
- No retry/backoff policy beyond "fail this source, log it, let the next scheduled run try again" —
  a more sophisticated retry strategy is deferred until an actual outage pattern is observed.
- No multi-instance/concurrency handling — this is assumed to run as a single scheduled job, not
  multiple overlapping instances.
