"""Run orchestration: drives each source independently so one failure never
wedges the others, resolves stale cursors into a full backfill, and writes
every record idempotently."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Optional

from . import db
from .adapters import ALL_SOURCES, build_adapter
from .adapters.base import FetchResult
from .models import RecordValidationError, StaleCursorError


@dataclass
class SourceResult:
    source: str
    mode: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    dead_lettered: int = 0
    status: str = "ok"
    error: Optional[str] = None

    @property
    def upserted(self) -> int:
        return self.inserted + self.updated


@dataclass
class RunSummary:
    run_id: str
    results: list[SourceResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.status == "ok" for r in self.results)


def _persist_batch(
    conn: sqlite3.Connection, source: str, adapter, fr: FetchResult, res: SourceResult
) -> None:
    """Normalize + upsert every raw record. Bad records are dead-lettered so
    the rest of the batch still lands."""
    res.fetched += len(fr.raw_records)
    for raw in fr.raw_records:
        try:
            rec = adapter.normalize(raw)
        except RecordValidationError as e:
            import json
            db.dead_letter(conn, source, str(e), json.dumps(raw, default=str))
            res.dead_lettered += 1
            continue
        outcome = db.upsert_record(conn, rec)
        if outcome == "inserted":
            res.inserted += 1
        elif outcome == "updated":
            res.updated += 1
        else:
            res.skipped += 1


def sync_source(
    conn: sqlite3.Connection,
    run_id: str,
    source: str,
    *,
    mode: str = "fake",
    fetch_mode: str = "incremental",  # "incremental" | "full"
    inject: Optional[set[str]] = None,
) -> SourceResult:
    """Sync a single source inside its own error boundary and transaction."""
    adapter = build_adapter(source, mode=mode, inject=inject)
    res = SourceResult(source=source, mode=fetch_mode)
    log_id = db.start_run(conn, run_id, source, fetch_mode)

    try:
        cursor = db.get_cursor(conn, source)

        if fetch_mode == "full":
            fr = adapter.fetch_full()
            res.mode = "full"
        else:
            try:
                fr = adapter.fetch_incremental(cursor)
            except StaleCursorError as e:
                # Cursor rejected — reset it and backfill everything. No data
                # is lost and the run does not crash.
                db.clear_cursor(conn, source)
                fr = adapter.fetch_full()
                res.mode = "full_backfill_fallback"
                res.error = f"stale cursor recovered: {e}"

        _persist_batch(conn, source, adapter, fr, res)

        # Cursor advances ONLY after the batch is durably persisted, so a crash
        # mid-run just re-fetches and re-upserts (safe, because writes are
        # idempotent) instead of skipping records.
        conn.commit()
        db.set_cursor(conn, source, fr.cursor, fr.cursor_type,
                      full_sync=res.mode.startswith("full"))
        conn.commit()

    except Exception as e:  # noqa: BLE001 — deliberate per-source boundary
        conn.rollback()
        res.status = "failed"
        res.error = f"{type(e).__name__}: {e}"

    db.finish_run(conn, log_id, mode=res.mode, fetched=res.fetched,
                  upserted=res.upserted, skipped=res.skipped,
                  dead_lettered=res.dead_lettered, status=res.status,
                  error=res.error)
    return res


def run_sync(
    conn: sqlite3.Connection,
    sources: Optional[list[str]] = None,
    *,
    mode: str = "fake",
    fetch_mode: str = "incremental",
    inject_map: Optional[dict[str, set[str]]] = None,
) -> RunSummary:
    """Sync several sources. Each is fully isolated: a failure in one is
    recorded and the loop moves on to the next."""
    sources = sources or ALL_SOURCES
    inject_map = inject_map or {}
    summary = RunSummary(run_id=uuid.uuid4().hex[:12])
    for source in sources:
        res = sync_source(conn, summary.run_id, source, mode=mode,
                          fetch_mode=fetch_mode, inject=inject_map.get(source))
        summary.results.append(res)
    return summary
