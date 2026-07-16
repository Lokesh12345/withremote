"""SQLite persistence: schema init, idempotent upsert, cursor store,
event-dedup ledger, dead-letter and run logging."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import CONFIG
from .models import Record

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or CONFIG.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()


# --------------------------------------------------------------------------- #
# Idempotent upsert                                                            #
# --------------------------------------------------------------------------- #
def upsert_record(conn: sqlite3.Connection, rec: Record) -> str:
    """Insert or update a record on its (source, source_id) natural key.

    Returns one of: "inserted", "updated", "skipped".

    Conflict resolution is last-write-wins by `source_updated_at`: an incoming
    record older than what we already stored is ignored ("skipped"), so a
    stale re-delivery cannot clobber newer data. Missing timestamps are treated
    as always-newer so we never silently drop data we can't order.
    """
    cur = conn.execute(
        "SELECT id, source_updated_at FROM records WHERE source = ? AND source_id = ?",
        (rec.source, rec.source_id),
    )
    existing = cur.fetchone()
    ts = now_iso()

    if existing is None:
        conn.execute(
            """INSERT INTO records
               (source, source_id, type, source_updated_at, title, email,
                amount, currency, status, occurred_at, raw_json, synced_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rec.source, rec.source_id, rec.type, rec.source_updated_at, rec.title,
             rec.email, rec.amount, rec.currency, rec.status, rec.occurred_at,
             rec.raw_json, ts),
        )
        return "inserted"

    # Row exists — decide whether the incoming version is newer.
    old_ts = existing["source_updated_at"]
    if rec.source_updated_at and old_ts and rec.source_updated_at < old_ts:
        return "skipped"

    conn.execute(
        """UPDATE records SET
               type = ?, source_updated_at = ?, title = ?, email = ?, amount = ?,
               currency = ?, status = ?, occurred_at = ?, raw_json = ?, synced_at = ?
           WHERE source = ? AND source_id = ?""",
        (rec.type, rec.source_updated_at, rec.title, rec.email, rec.amount,
         rec.currency, rec.status, rec.occurred_at, rec.raw_json, ts,
         rec.source, rec.source_id),
    )
    return "updated"


# --------------------------------------------------------------------------- #
# Cursor store                                                                 #
# --------------------------------------------------------------------------- #
def get_cursor(conn: sqlite3.Connection, source: str) -> Optional[str]:
    row = conn.execute(
        "SELECT cursor FROM sync_state WHERE source = ?", (source,)
    ).fetchone()
    return row["cursor"] if row else None


def set_cursor(
    conn: sqlite3.Connection,
    source: str,
    cursor: Optional[str],
    cursor_type: str = "",
    full_sync: bool = False,
) -> None:
    ts = now_iso()
    conn.execute(
        """INSERT INTO sync_state (source, cursor, cursor_type, last_full_sync_at,
                                   last_success_at, updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(source) DO UPDATE SET
               cursor = excluded.cursor,
               cursor_type = excluded.cursor_type,
               last_full_sync_at = CASE WHEN ? THEN excluded.last_full_sync_at
                                        ELSE sync_state.last_full_sync_at END,
               last_success_at = excluded.last_success_at,
               updated_at = excluded.updated_at""",
        (source, cursor, cursor_type, ts if full_sync else None, ts, ts, full_sync),
    )


def clear_cursor(conn: sqlite3.Connection, source: str) -> None:
    """Used when a cursor goes stale — reset before a full backfill."""
    conn.execute("UPDATE sync_state SET cursor = NULL WHERE source = ?", (source,))


# --------------------------------------------------------------------------- #
# Webhook / event dedup ledger                                                 #
# --------------------------------------------------------------------------- #
def already_processed(conn: sqlite3.Connection, source: str, delivery_id: str) -> bool:
    """Record a delivery id; return True if it was seen before.

    The INSERT OR IGNORE + rowcount check is atomic, so two concurrent
    deliveries of the same id cannot both win.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO processed_events (source, delivery_id, processed_at) "
        "VALUES (?,?,?)",
        (source, delivery_id, now_iso()),
    )
    return cur.rowcount == 0


# --------------------------------------------------------------------------- #
# Dead letter + run log                                                        #
# --------------------------------------------------------------------------- #
def dead_letter(conn: sqlite3.Connection, source: str, reason: str, raw_json: str) -> None:
    conn.execute(
        "INSERT INTO dead_letter (source, reason, raw_json, created_at) VALUES (?,?,?,?)",
        (source, reason, raw_json, now_iso()),
    )


def start_run(conn: sqlite3.Connection, run_id: str, source: str, mode: str) -> int:
    cur = conn.execute(
        "INSERT INTO run_log (run_id, source, mode, status, started_at) "
        "VALUES (?,?,?,?,?)",
        (run_id, source, mode, "running", now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    row_id: int,
    *,
    mode: str,
    fetched: int,
    upserted: int,
    skipped: int,
    dead_lettered: int,
    status: str,
    error: Optional[str] = None,
) -> None:
    conn.execute(
        """UPDATE run_log SET mode = ?, fetched = ?, upserted = ?, skipped = ?,
               dead_lettered = ?, status = ?, error = ?, finished_at = ?
           WHERE id = ?""",
        (mode, fetched, upserted, skipped, dead_lettered, status, error,
         now_iso(), row_id),
    )
    conn.commit()
