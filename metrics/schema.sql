-- Metrics service schema (Supabase Postgres).
-- The `collected_transactions` view is created separately from canonical.py so
-- the allow-list has exactly one definition.

CREATE TABLE IF NOT EXISTS transactions (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,      -- stripe | billing | pos | ...
    source_id     TEXT        NOT NULL,      -- natural id in that source
    raw_status    TEXT        NOT NULL,      -- source's own vocabulary
    amount_minor  BIGINT      NOT NULL,      -- integer minor units, never float
    currency      TEXT        NOT NULL,      -- ISO-4217, upper-case
    occurred_at   TIMESTAMPTZ NOT NULL,      -- when the money event happened
    raw_json      JSONB,
    -- idempotency: re-ingesting the same record updates in place
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_txn_occurred ON transactions (occurred_at);
CREATE INDEX IF NOT EXISTS idx_txn_source_status ON transactions (source, raw_status);

-- Maps each source's raw status vocabulary onto the canonical vocabulary.
-- A (source, raw_status) with NO row here is deliberately unmapped -> the view
-- excludes it (UNKNOWN), so it can never be counted as revenue by accident.
CREATE TABLE IF NOT EXISTS status_map (
    source            TEXT NOT NULL,
    raw_status        TEXT NOT NULL,
    canonical_status  TEXT NOT NULL CHECK (canonical_status IN
        ('COLLECTED','PENDING','REFUNDED','FAILED','VOIDED','UNKNOWN')),
    PRIMARY KEY (source, raw_status)
);
