-- syncpipe schema. One normalized table plus the bookkeeping tables that make
-- the pipeline idempotent, resumable, and honest about failures.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- The single normalized destination for all three sources.
CREATE TABLE IF NOT EXISTS records (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source             TEXT    NOT NULL,          -- hubspot | stripe | gcal
    source_id          TEXT    NOT NULL,          -- natural id from the source
    type               TEXT    NOT NULL,          -- contact | payment | event
    source_updated_at  TEXT,                      -- ISO-8601 UTC (last-write-wins)
    title              TEXT,
    email              TEXT,
    amount             REAL,
    currency           TEXT,
    status             TEXT,
    occurred_at        TEXT,
    raw_json           TEXT    NOT NULL,          -- original payload, verbatim
    synced_at          TEXT    NOT NULL,          -- when we last wrote this row
    -- The natural key. Every write is an upsert on this pair, so re-runs and
    -- double-fired webhooks can never create duplicate rows.
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_records_type ON records (type);
CREATE INDEX IF NOT EXISTS idx_records_source ON records (source);

-- Durable per-source cursor store for incremental fetches.
CREATE TABLE IF NOT EXISTS sync_state (
    source             TEXT PRIMARY KEY,
    cursor             TEXT,                      -- timestamp / sync-token / id
    cursor_type        TEXT,                      -- describes how to use cursor
    last_full_sync_at  TEXT,
    last_success_at    TEXT,
    updated_at         TEXT
);

-- Webhook/event delivery ledger. Second delivery of the same id is a no-op,
-- giving idempotency even before we reach the records upsert.
CREATE TABLE IF NOT EXISTS processed_events (
    source        TEXT NOT NULL,
    delivery_id   TEXT NOT NULL,
    processed_at  TEXT NOT NULL,
    PRIMARY KEY (source, delivery_id)
);

-- Quarantine for malformed / unparseable records. Keeps a bad record from
-- wedging the rest of its batch.
CREATE TABLE IF NOT EXISTS dead_letter (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    reason        TEXT NOT NULL,
    raw_json      TEXT,
    created_at    TEXT NOT NULL
);

-- Per-run, per-source outcome. The surface that proves the pipeline is not
-- lying about what it did.
CREATE TABLE IF NOT EXISTS run_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL,
    source         TEXT NOT NULL,
    mode           TEXT NOT NULL,       -- incremental | full | full_backfill_fallback
    fetched        INTEGER NOT NULL DEFAULT 0,
    upserted       INTEGER NOT NULL DEFAULT 0,
    skipped        INTEGER NOT NULL DEFAULT 0,  -- stale (older) writes ignored
    dead_lettered  INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL,       -- ok | failed
    error          TEXT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT
);
