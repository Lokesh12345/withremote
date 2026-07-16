"""Supabase Postgres access for the metrics service."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psycopg

from . import canonical
from .config import DATABASE_URL

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set (see .env)")
    return psycopg.connect(DATABASE_URL, connect_timeout=15)


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text())
    conn.execute(canonical.collected_view_sql())  # allow-list view, generated once
    conn.commit()


def upsert_transaction(
    conn: psycopg.Connection,
    *,
    source: str,
    source_id: str,
    raw_status: str,
    amount_minor: int,
    currency: str,
    occurred_at: datetime,
    raw: Optional[dict[str, Any]] = None,
) -> None:
    """Idempotent on (source, source_id) — carries the PS1 guarantee forward."""
    conn.execute(
        """
        INSERT INTO transactions
            (source, source_id, raw_status, amount_minor, currency, occurred_at, raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            raw_status = EXCLUDED.raw_status,
            amount_minor = EXCLUDED.amount_minor,
            currency = EXCLUDED.currency,
            occurred_at = EXCLUDED.occurred_at,
            raw_json = EXCLUDED.raw_json
        """,
        (source, source_id, raw_status, amount_minor, currency.upper(),
         occurred_at, json.dumps(raw or {})),
    )


def upsert_status_map(conn: psycopg.Connection, source: str, raw_status: str,
                      canonical_status: str) -> None:
    conn.execute(
        """INSERT INTO status_map (source, raw_status, canonical_status)
           VALUES (%s,%s,%s)
           ON CONFLICT (source, raw_status) DO UPDATE
             SET canonical_status = EXCLUDED.canonical_status""",
        (source, raw_status, canonical_status),
    )


def unmapped_statuses(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Raw statuses present in transactions but absent from status_map. These
    fall through to UNKNOWN and are excluded from revenue — surfaced here so the
    exclusion is visible, never silent."""
    rows = conn.execute(
        """SELECT t.source, t.raw_status, COUNT(*) AS n
           FROM transactions t
           LEFT JOIN status_map m
             ON m.source = t.source AND m.raw_status = t.raw_status
           WHERE m.canonical_status IS NULL
           GROUP BY t.source, t.raw_status
           ORDER BY t.source, t.raw_status"""
    ).fetchall()
    return [{"source": r[0], "raw_status": r[1], "count": int(r[2])} for r in rows]
