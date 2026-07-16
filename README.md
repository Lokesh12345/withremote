# Backend assignment — data correctness & failure handling

Two backend problems, both about **data that doesn't lie**: correctness under
failure, and one metric that never drifts. No UI — CLIs, a couple of APIs, and
tests that prove the guarantees.

### Working screenshots Requirement -1
<img width="1534" height="482" alt="image" src="https://github.com/user-attachments/assets/a56d25f8-17de-46b1-9fb2-a830abde3976" />
<img width="1928" height="1114" alt="image" src="https://github.com/user-attachments/assets/7d76376d-1dd9-4063-8d17-1fd2665b035e" />
<img width="1880" height="764" alt="image" src="https://github.com/user-attachments/assets/fb1d99cb-adf7-432e-95f1-eccc1fe036a9" />
<img width="1630" height="484" alt="image" src="https://github.com/user-attachments/assets/671de5c7-275a-4831-93bf-6a14b8b4d78f" />


### Working screenshots Requirement -2
<img width="1882" height="618" alt="image" src="https://github.com/user-attachments/assets/5dccb68c-432b-4dc9-9db0-4b2c2086a080" />



## What's here

| | Problem | Solution | Verified against |
|---|---------|----------|------------------|
| **PS1** | A sync pipeline that doesn't lie or duplicate data | [`syncpipe/`](#syncpipe) — normalize 3 sources, stale-cursor→backfill, idempotent writes, fault isolation | live HubSpot + Stripe + Google Calendar |
| **PS2** | One revenue number that never drifts | [`metrics/`](#problem-statement-2--canonical-revenue-metric-metrics) — allow-list "collected", two agreeing views, single-definition guard | live Stripe + Supabase Postgres |

## Shared setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in creds for live/Supabase; fake mode needs none
```

`.env` is git-ignored (secrets never committed). PS1 runs fully offline in fake
mode; PS2 needs a Supabase `DATABASE_URL`. See `.env.example` for every variable.

---

# syncpipe

**(PS1)** A resilient sync pipeline that ingests records from three
differently-shaped sources — **HubSpot** (CRM contacts), **Stripe** (payments),
and **Google Calendar** (events) — into **one normalized SQLite schema**.

It is built around the four correctness/failure requirements of the assignment:

1. **Normalization** — each source names and shapes fields differently; all are
   mapped into one unified `Record`.
2. **Stale-cursor → full backfill** — when an incremental cursor is rejected
   (e.g. Google Calendar `410 Gone` on an expired `syncToken`), the pipeline
   falls back to a full fetch instead of losing data or crashing.
3. **Idempotent writes** — every write is an upsert on the natural key
   `(source, source_id)`, so a re-run or a double-fired webhook never creates a
   duplicate row.
4. **Fault isolation** — a source that is down or returns garbage is confined to
   its own error boundary; the other two still land their data.

No UI. Driven by a CLI plus a webhook receiver, and proven by three demo scripts.

## Verified against live APIs

The pipeline has been run end-to-end against real accounts, not just fixtures:

| Source | Live result |
|--------|-------------|
| HubSpot | 2 contacts fetched, normalized, idempotent on re-run |
| Stripe (test mode) | 3 payments fetched, normalized (minor→major units), idempotent |
| Google Calendar | 333 events fetched, normalized; **stale syncToken → real full backfill**, 0 data loss, 0 duplicates |

Two live-only bugs were caught and fixed this way (e.g. Stripe SDK objects are
not `dict()`-able — the adapter serializes via `json.loads(str(pi))`).

## Assignment requirements → where each is satisfied

| # | Requirement | Implementation | Proof |
|---|-------------|----------------|-------|
| 1 | Ingest 3 differently-shaped sources into one normalized schema | `adapters/*.normalize()` → `Record` → `records` table | `status` shows contact/payment/event unified |
| 2 | Fall back to full backfill when a cursor goes stale (410 / expired token) | `StaleCursorError` → orchestrator clears cursor, full-fetches | `demos/demo_stale_cursor.sh` + live Google 410 |
| 3 | Idempotent writes (double webhook / re-run → no dupes) | upsert on `UNIQUE(source, source_id)` + `processed_events` ledger | `demos/demo_idempotency.sh` |
| 4 | One source down/garbage doesn't wedge the others | per-source try/except + transaction; per-record dead-letter | `demos/demo_fault_isolation.sh` |

---

## Quick start (fake mode — no accounts needed)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# run the three proofs
bash demos/demo_idempotency.sh       # re-run + double webhook → no dupes
bash demos/demo_stale_cursor.sh      # rejected cursor → full backfill, no loss
bash demos/demo_fault_isolation.sh   # 1 down + 1 garbage → other 2 still land
```

Fake mode serves deterministic fixtures and never touches the network, so the
failure modes are reproducible on demand.

## CLI

```bash
python -m syncpipe.cli init-db
python -m syncpipe.cli sync --source all                 # incremental, all sources
python -m syncpipe.cli sync --source gcal --mode full    # force a full fetch
python -m syncpipe.cli status                            # counts, cursors, dead-letter, runs

# inject faults (fake mode): FAULT:SOURCE
python -m syncpipe.cli sync --source gcal --inject stale-cursor:gcal
python -m syncpipe.cli sync --source all  --inject down:stripe --inject garbage:hubspot
```

Faults: `stale-cursor` (reject the incremental cursor), `down` (source
unreachable), `garbage` (emit a malformed record).

## Webhook receiver

```bash
uvicorn syncpipe.webhook:app --port 8000
# local contract (works without secrets, dedups on delivery_id):
curl -XPOST localhost:8000/webhook/stripe \
  -d '{"delivery_id":"evt_1","records":[{"id":"pi_9","amount":500,"currency":"usd","status":"succeeded","created":1752660000}]}'
```

Both the poll job and the webhook go through the **same** normalize + idempotent
upsert, and webhooks are additionally deduped on their delivery id.

---

## Data model (`syncpipe/schema.sql`)

| table | purpose |
|-------|---------|
| `records` | the one normalized table; `UNIQUE(source, source_id)` is the idempotency key |
| `sync_state` | durable per-source cursor (timestamp / sync-token) |
| `processed_events` | webhook delivery-id ledger for dedup |
| `dead_letter` | quarantine for malformed records |
| `run_log` | per-run, per-source outcome (fetched / upserted / skipped / dead / status) |

### Field mapping

| unified | HubSpot contact | Stripe payment | GCal event |
|---|---|---|---|
| `source_id` | `id` | `id` | `id` |
| `source_updated_at` | `properties.lastmodifieddate` | `created` (→ISO) | `updated` |
| `title` | `firstname` + `lastname` | `description` | `summary` |
| `email` | `properties.email` | `receipt_email` | `organizer.email` |
| `amount`/`currency` | — | `amount`/100, `currency` | — |
| `status` | `lifecyclestage` | `status` | `status` |
| `occurred_at` | `createdate` | `created` (→ISO) | `start.dateTime` |

---

## How each requirement is met

- **Idempotency** — `db.upsert_record` upserts on `(source, source_id)` with
  last-write-wins by `source_updated_at`, so a stale re-delivery can't clobber
  newer data. The cursor is advanced **only after** the batch is durably
  committed, so a crash mid-run just re-fetches and re-upserts (safe).
- **Stale cursor** — adapters raise `StaleCursorError` when a cursor is rejected
  (real `410` for Google Calendar; injectable for HubSpot/Stripe, whose cursors
  don't expire). The orchestrator clears the cursor and runs a full backfill,
  logging `mode=full_backfill_fallback`.
- **Fault isolation** — `orchestrator.sync_source` wraps each source in its own
  try/except and transaction. A failure is recorded in `run_log` and the loop
  continues. Malformed records are dead-lettered per-record.

## Going live

Fill `.env` (see `.env.example`) and pass `--live`:

- **HubSpot**: create a private app, grant `crm.objects.contacts.read`, set
  `HUBSPOT_ACCESS_TOKEN`.
- **Stripe**: use a **test-mode secret key** `sk_test_...` in `STRIPE_API_KEY`.
- **Google Calendar**: download an OAuth desktop client JSON to
  `google_credentials.json`; first `--live` run opens a consent flow and caches
  the token.

```bash
python -m syncpipe.cli sync --source all --live
```

## Layout

```
syncpipe/
  config.py         env-backed config
  models.py         Record + typed errors
  schema.sql        the 5 tables
  db.py             upsert, cursor store, dedup ledger, dead-letter, run log
  orchestrator.py   per-source isolation, stale-cursor fallback
  adapters/         hubspot / stripe / gcal (live + fake) + fixtures
  cli.py            init-db / sync / status
  webhook.py        FastAPI receiver (same upsert path)
demos/              the three proof scripts
```

---

# Problem Statement 2 — canonical revenue metric (metrics/)

One "collected revenue" number that never drifts, over multiple sources with
different status vocabularies, stored in **Supabase Postgres**.

## The four requirements → where each is satisfied

| # | Requirement | Implementation | Proof |
|---|-------------|----------------|-------|
| 1 | Canonical "collected" via **allow-list**, not exclusion list | `status_map` maps each source's raw status → canonical enum; `collected_transactions` view keeps only `canonical_status ∈ COLLECTED_ALLOW_LIST`; unmapped statuses INNER-join out | `tests/test_allowlist.py` |
| 2 | Same number through two views that always agree | `/metrics/revenue` (summary) and `/metrics/revenue/breakdown` (day/week) both call the single `collected_revenue()` | `tests/test_agreement.py` (summary == Σ breakdown, per currency) |
| 3 | Invariant when a new source/status is added | allow-list default is $0; new unmapped status changes nothing and is surfaced by `/metrics/unmapped` | `test_new_status_does_not_change_revenue` |
| 4 | A second divergent computation is caught | revenue is summed in exactly one place; a static guard fails the build otherwise | `tests/test_single_definition.py` (demonstrated failing on a rogue file) |

## Anti-drift discipline
- **Money as integer minor units** (`BIGINT`), never float. `amount_minor` is the authoritative value; the major-unit string is presentation only.
- **UTC everywhere**; day/week buckets cut with `date_trunc(... AT TIME ZONE 'UTC')` so both views share boundaries.
- **Half-open ranges `[start, end)`** in both views — no boundary double-counting.
- **Per-currency totals** — USD and EUR are never summed into one number.

## Sources & vocabularies (deliberately different)

| source | "collected" is | also emits |
|--------|----------------|-----------|
| `stripe` (real, test mode) | `succeeded` | `processing`, `canceled`, … |
| `billing` (synthetic) | `paid` | `open`, `void`, `refunded` |
| `pos` (synthetic) | `completed` | `pending`, `failed`, **`disputed`** ← left unmapped on purpose |

## Run it

```bash
# DATABASE_URL must point at Supabase (Session pooler URI). See .env.example.
python -m metrics.seed                       # schema + status map + sample txns
uvicorn metrics.api:app --port 8100

curl "localhost:8100/metrics/revenue?start=2026-07-01&end=2026-08-01"
curl "localhost:8100/metrics/revenue/breakdown?start=2026-07-01&end=2026-08-01&bucket=day"
curl "localhost:8100/metrics/unmapped"

pytest tests/ -v                             # the four drift guards
```

Verified against live Supabase: summary `USD 396.99 / EUR 80.00` equals the
day-by-day breakdown summed; `pos/disputed` (9000) is excluded and surfaced;
the guard test fails when a rogue `SUM(amount_minor)` is added elsewhere.

## Live API — every endpoint (curl)

Deployed on Render: **https://revenue-metrics-5dum.onrender.com**

```bash
BASE="https://revenue-metrics-5dum.onrender.com"   # or http://localhost:8100 locally

# 1) health check
curl "$BASE/health"

# 2) summary total — collected revenue per currency for a date range
curl "$BASE/metrics/revenue?start=2026-07-01&end=2026-08-01"

# 3) breakdown — same number, per day
curl "$BASE/metrics/revenue/breakdown?start=2026-07-01&end=2026-08-01&bucket=day"

# 4) breakdown — per week
curl "$BASE/metrics/revenue/breakdown?start=2026-07-01&end=2026-08-01&bucket=week"

# 5) unmapped statuses — excluded from revenue, surfaced (never silent)
curl "$BASE/metrics/unmapped"
```

Both views agree: the buckets in (3) sum to the totals in (2) — `USD 396.99`,
`EUR 80.00`.

> Note: the free Render instance sleeps after inactivity. The first request may
> take ~30s to wake, and Cloudflare can briefly cache a cold-start `404`. If you
> hit one, append a unique query param to bypass the edge cache, e.g.
> `...&cb=1`.

### PS1 webhook receiver (run locally)

```bash
uvicorn syncpipe.webhook:app --port 8000

curl "http://localhost:8000/health"

# same webhook fired twice -> exactly one row (idempotent)
curl -XPOST "http://localhost:8000/webhook/stripe" \
  -H 'Content-Type: application/json' \
  -d '{"delivery_id":"evt_1","records":[{"id":"pi_9","amount":500,"currency":"usd","status":"succeeded","created":1752660000}]}'

# sources: /webhook/stripe · /webhook/hubspot · /webhook/gcal
```

## Metrics layout
```
metrics/
  canonical.py   THE single source of truth: allow-list + collected_revenue()
  schema.sql     transactions + status_map
  db.py          Supabase access, idempotent upsert, unmapped diagnostic
  seed.py        real Stripe + 2 synthetic sources, the status map
  api.py         /metrics/revenue, /revenue/breakdown, /unmapped
  config.py      DATABASE_URL (auto-encodes a raw '@' in the password)
tests/           agreement · allow-list · single-definition guard
```
