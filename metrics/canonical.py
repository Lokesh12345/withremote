"""THE single source of truth for "collected revenue".

Everything about the canonical number lives here and ONLY here:
  * the set of canonical statuses,
  * the ALLOW-LIST of statuses that count as collected,
  * the one SQL view that applies the allow-list,
  * the one function that sums money over a date range.

Both API endpoints call `collected_revenue()`. Nothing else in the codebase is
permitted to sum transaction amounts or hardcode a status literal — the guard
test (`tests/test_single_definition.py`) fails the build if it finds a second
computation. That is what stops the number from drifting.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# --- canonical vocabulary --------------------------------------------------- #
# Every raw source status is mapped (via the status_map table) to exactly one of
# these. Anything with no mapping is treated as UNKNOWN and therefore excluded.
CANONICAL_STATUSES = (
    "COLLECTED",   # money actually collected and retained
    "PENDING",     # not yet collected
    "REFUNDED",    # collected then given back (incl. chargebacks)
    "FAILED",      # never collected
    "VOIDED",      # cancelled before collection
    "UNKNOWN",     # unmapped / unexpected — never counts
)

# The ALLOW-LIST. This is the whole definition of "collected". It is an
# allow-list, NOT an exclusion list: a brand-new status the system has never
# seen contributes $0 until someone deliberately maps it to COLLECTED.
COLLECTED_ALLOW_LIST = frozenset({"COLLECTED"})

VIEW = "collected_transactions"


def collected_view_sql() -> str:
    """DDL for the one view that encodes the allow-list. Generated from
    COLLECTED_ALLOW_LIST so the allow-list is defined in exactly one place."""
    allowed = ", ".join(f"'{s}'" for s in sorted(COLLECTED_ALLOW_LIST))
    return f"""
    CREATE OR REPLACE VIEW {VIEW} AS
    SELECT t.id, t.source, t.source_id, t.raw_status, m.canonical_status,
           t.amount_minor, t.currency, t.occurred_at
    FROM transactions t
    -- INNER join: a transaction whose (source, raw_status) has no mapping is
    -- dropped entirely, so unknown statuses cannot leak in as revenue.
    JOIN status_map m
      ON m.source = t.source AND m.raw_status = t.raw_status
    WHERE m.canonical_status IN ({allowed});
    """


@dataclass
class RevenueRow:
    bucket: Optional[str]     # ISO date for breakdown, None for summary
    currency: str
    amount_minor: int         # exact integer minor units — no float drift
    txn_count: int


def collected_revenue(
    conn,
    start: datetime,
    end: datetime,
    bucket: Optional[str] = None,   # None | "day" | "week"
) -> list[RevenueRow]:
    """The one and only revenue computation.

    * Range is half-open [start, end) so adjacent ranges never double-count.
    * Buckets are cut in UTC so the summary and breakdown always share
      identical boundaries.
    * Results are grouped per currency; currencies are never summed together.
    """
    if bucket not in (None, "day", "week"):
        raise ValueError(f"bucket must be None, 'day' or 'week', got {bucket!r}")

    if bucket is None:
        sql = f"""
            SELECT NULL::text AS bucket, currency,
                   SUM(amount_minor)::bigint AS amount_minor,
                   COUNT(*)::bigint AS txn_count
            FROM {VIEW}
            WHERE occurred_at >= %(start)s AND occurred_at < %(end)s
            GROUP BY currency
            ORDER BY currency
        """
    else:
        sql = f"""
            SELECT to_char(date_trunc(%(bucket)s,
                       occurred_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD') AS bucket,
                   currency,
                   SUM(amount_minor)::bigint AS amount_minor,
                   COUNT(*)::bigint AS txn_count
            FROM {VIEW}
            WHERE occurred_at >= %(start)s AND occurred_at < %(end)s
            GROUP BY 1, currency
            ORDER BY 1, currency
        """
    params = {"start": start, "end": end, "bucket": bucket}
    rows = conn.execute(sql, params).fetchall()
    return [RevenueRow(bucket=r[0], currency=r[1],
                       amount_minor=int(r[2] or 0), txn_count=int(r[3])) for r in rows]
