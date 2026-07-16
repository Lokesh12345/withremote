"""The definition is an allow-list, not an exclusion list: an unexpected/new
status must contribute $0 and be surfaced, never silently counted."""
from datetime import datetime, timezone

from metrics import canonical, db


def _dt(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_unmapped_status_is_excluded_and_surfaced(conn):
    # 'pos/disputed' (9000) and 'pos/failed' (4000) both fall on 2026-07-05 and
    # are not COLLECTED, so collected revenue that day is 0.
    rows = canonical.collected_revenue(conn, _dt("2026-07-05"), _dt("2026-07-06"))
    assert rows == [], f"non-collected statuses leaked as revenue: {rows}"

    # The unmapped status is visible via the diagnostic, not hidden.
    unmapped = {(u["source"], u["raw_status"]) for u in db.unmapped_statuses(conn)}
    assert ("pos", "disputed") in unmapped


def test_new_status_does_not_change_revenue(conn):
    """Simulate a brand-new status arriving. Because it isn't in the allow-list
    (no status_map row), revenue must be unchanged. Done inside a rolled-back
    transaction so the DB is left untouched."""
    s, e = _dt("2026-07-01"), _dt("2026-07-06")
    before = {r.currency: r.amount_minor for r in canonical.collected_revenue(conn, s, e)}

    with conn.transaction(force_rollback=True):
        db.upsert_transaction(
            conn, source="pos", source_id="ghost-new",
            raw_status="quantum_superpaid",  # never seen before, unmapped
            amount_minor=9_999_999, currency="USD",
            occurred_at=_dt("2026-07-03T12:00:00"), raw={"test": True})
        after = {r.currency: r.amount_minor
                 for r in canonical.collected_revenue(conn, s, e)}

    assert after == before, (
        f"an unmapped new status changed revenue (exclusion-list bug): "
        f"{before} -> {after}")
