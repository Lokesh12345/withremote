"""The two views must always agree: summary == sum(breakdown), per currency,
for any range and any bucket. This is the core anti-drift invariant."""
from datetime import datetime, timezone

from metrics import canonical

RANGES = [
    ("2026-07-01", "2026-07-06"),   # covers all synthetic
    ("2026-07-01", "2026-08-01"),   # covers synthetic + live stripe (mid-July)
    ("2026-07-02", "2026-07-05"),   # a partial window
    ("2000-01-01", "2100-01-01"),   # everything
]


def _dt(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _by_currency(rows):
    return {r.currency: r.amount_minor for r in rows}


def test_summary_equals_breakdown(conn):
    for start, end in RANGES:
        s, e = _dt(start), _dt(end)
        summary = _by_currency(canonical.collected_revenue(conn, s, e))
        for bucket in ("day", "week"):
            series = canonical.collected_revenue(conn, s, e, bucket=bucket)
            agg = {}
            for r in series:
                agg[r.currency] = agg.get(r.currency, 0) + r.amount_minor
            assert agg == summary, (
                f"drift: range {start}..{end} bucket={bucket}: "
                f"summary={summary} != breakdown_sum={agg}")


def test_counts_also_agree(conn):
    s, e = _dt("2026-07-01"), _dt("2026-07-06")
    summary = {r.currency: r.txn_count for r in canonical.collected_revenue(conn, s, e)}
    series = canonical.collected_revenue(conn, s, e, bucket="day")
    agg = {}
    for r in series:
        agg[r.currency] = agg.get(r.currency, 0) + r.txn_count
    assert agg == summary
