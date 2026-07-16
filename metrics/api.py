"""Metrics HTTP API.

Two views of the SAME number:
  GET /metrics/revenue            -> summary total per currency
  GET /metrics/revenue/breakdown  -> per day/week, per currency
Both delegate to canonical.collected_revenue(); neither computes anything
itself, so they cannot disagree.

  GET /metrics/unmapped           -> raw statuses excluded as UNKNOWN
  GET /health

Run:  uvicorn metrics.api:app --port 8100
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from . import canonical, db

app = FastAPI(title="canonical revenue metrics")

# Minor-unit exponent for presentation only. The canonical value is the integer
# amount_minor; major is derived just for human display.
_EXPONENT = {"JPY": 0, "KRW": 0}


def _major(amount_minor: int, currency: str) -> str:
    exp = _EXPONENT.get(currency.upper(), 2)
    return str((Decimal(amount_minor) / (Decimal(10) ** exp)).quantize(
        Decimal(1).scaleb(-exp)))


def _parse(ts: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        raise HTTPException(422, f"{field} must be ISO-8601 (date or datetime)")
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _serialize(rows: list[canonical.RevenueRow], with_bucket: bool) -> list[dict]:
    out = []
    for r in rows:
        item = {"currency": r.currency, "amount_minor": r.amount_minor,
                "amount": _major(r.amount_minor, r.currency), "txn_count": r.txn_count}
        if with_bucket:
            item = {"bucket": r.bucket, **item}
        out.append(item)
    return out


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics/revenue")
def revenue(start: str = Query(...), end: str = Query(...)) -> dict:
    s, e = _parse(start, "start"), _parse(end, "end")
    with db.connect() as conn:
        rows = canonical.collected_revenue(conn, s, e, bucket=None)
    return {"definition": "collected", "allow_list": sorted(canonical.COLLECTED_ALLOW_LIST),
            "start": s.isoformat(), "end": e.isoformat(),
            "totals": _serialize(rows, with_bucket=False)}


@app.get("/metrics/revenue/breakdown")
def breakdown(start: str = Query(...), end: str = Query(...),
              bucket: str = Query("day", pattern="^(day|week)$")) -> dict:
    s, e = _parse(start, "start"), _parse(end, "end")
    with db.connect() as conn:
        rows = canonical.collected_revenue(conn, s, e, bucket=bucket)
    return {"definition": "collected", "allow_list": sorted(canonical.COLLECTED_ALLOW_LIST),
            "start": s.isoformat(), "end": e.isoformat(), "bucket": bucket,
            "series": _serialize(rows, with_bucket=True)}


@app.get("/metrics/unmapped")
def unmapped() -> dict:
    with db.connect() as conn:
        return {"unmapped": db.unmapped_statuses(conn)}
