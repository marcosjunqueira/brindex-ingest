---
name: run-brindex-ingest
description: Build, run, and smoke-test brindex-ingest — the CLI that downloads Tesouro Direto/PTAX/CDI and upserts them into a SQLite database. Use when asked to run brindex-ingest, start/build it, test it, or verify the CLI works end-to-end against the live sources.
---

`brindex-ingest` is a one-shot CLI (console script `brindex-ingest`, entrypoint
`brindex_ingest.main:main`), not a server — there's no window or socket to attach to.
Drive it via `.claude/skills/run-brindex-ingest/driver.sh`, which builds the venv, runs
the (network-free, fixture-based) unit tests, then runs the real CLI against a scratch
SQLite db hitting the live BCB/Tesouro endpoints, and checks the result twice (to prove
the upsert idempotency the whole project is built around).

All paths below are relative to the repo root (`brindex-ingest/`).

## Prerequisites

Nothing beyond Python 3.12+ and `venv` — no system packages needed (pure-Python deps:
`requests`, `xlrd`).

## Setup / Build

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

(The driver does this itself if `.venv` doesn't exist yet — you don't need to run it
by hand first.)

## Run (agent path)

```bash
.claude/skills/run-brindex-ingest/driver.sh                    # defaults to --source cdi
.claude/skills/run-brindex-ingest/driver.sh --source ptax
.claude/skills/run-brindex-ingest/driver.sh --source all       # slow: downloads 3 XLS files (~100-160KB each)
```

It installs/builds, runs `pytest`, then runs `brindex-ingest` twice against a temp
SQLite db (deleted on exit — this is a smoke test, not a way to produce a keeper
database) and prints the resulting `series`/`points` row counts plus a few sample rows
after each run, so you can see the second run left the count unchanged (idempotent
upsert) while still succeeding.

Default source is `cdi` because it's the cheapest live check (one small JSON GET) that
still exercises the full path: network fetch → parse → upsert → idempotent re-run.
`ptax` is similarly cheap. `all`/`treasury-direct` additionally download three ~100–
160KB XLS files from the Tesouro CDN — still fast, just heavier.

## Run (human path)

To actually keep the resulting database (not a throwaway smoke-test db):

```bash
.venv/bin/brindex-ingest --db /path/you/choose/brindex.sqlite --source all
```

`--source` accepts `treasury-direct`, `ptax`, `cdi`, or `all` (default). `--since
YYYY-MM-DD` controls the PTAX/CDI backfill window (default: 30 days back); ignored by
`treasury-direct`, which always ingests the full current-year XLS history.

## Test

```bash
.venv/bin/pytest -q
```

18 tests, all fixture-based (`tests/fixtures/`) — no network calls, runs in well under a
second.

## Gotchas

- **CDI (BCB SGS series 4391) is monthly, not daily** — one JSON entry per calendar
  month, dated the 1st (`{"data": "01/09/2026", "valor": "0.26"}`). A `--since 30-days`
  window can legitimately produce only 1–2 rows; that's correct, not a bug.
- **Treasury Direct produces *two* points per XLS row** — `TD:<SERIES>:<maturity>:BUY`
  and `:SELL` (invest vs. redeem price), so `--source treasury-direct` series counts are
  2× the number of maturities across the three fixture types (LFT/LTN/NTN-B Principal).
- **A shell script's own `cd` to find the repo root must be relative to the script's own
  location (`${BASH_SOURCE[0]}`), not the caller's `$PWD`** — `git rev-parse
  --show-toplevel` run from an arbitrary invocation directory (e.g. driving the script
  via an absolute path from `/tmp`) fails with "not a git repository" before it even gets
  a chance to `cd`. `driver.sh` resolves its own directory first for exactly this reason.

## Troubleshooting

- **`ERROR: file:///tmp does not appear to be a Python project`**: you're running the
  driver from a directory outside the repo and it fell back to `git rev-parse` in the
  wrong cwd. Shouldn't happen with the current `driver.sh` (fixed via `BASH_SOURCE`), but
  if you see this after editing the script, check that the `cd` at the top still resolves
  relative to `${BASH_SOURCE[0]}`, not `$PWD`.
