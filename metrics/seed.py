"""Seed the metrics DB: the status map plus sample transactions from three
sources with three different status vocabularies.

  stripe  : succeeded / processing / canceled ...   (REAL, test mode)
  billing : paid / open / void / refunded           (synthetic)
  pos     : completed / pending / failed / disputed (synthetic)

`disputed` on `pos` is intentionally left OUT of the status map to demonstrate
that an unexpected status contributes $0 and is surfaced by /metrics/unmapped
rather than silently counted.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import db
from .config import STRIPE_API_KEY

# (source, raw_status) -> canonical_status.  Note: pos/disputed is absent.
STATUS_MAP = [
    # Stripe PaymentIntent vocabulary
    ("stripe", "succeeded", "COLLECTED"),
    ("stripe", "processing", "PENDING"),
    ("stripe", "requires_payment_method", "PENDING"),
    ("stripe", "canceled", "VOIDED"),
    ("stripe", "refunded", "REFUNDED"),
    # Synthetic "billing" vocabulary
    ("billing", "paid", "COLLECTED"),
    ("billing", "open", "PENDING"),
    ("billing", "void", "VOIDED"),
    ("billing", "refunded", "REFUNDED"),
    # Synthetic "pos" vocabulary  (NB: 'disputed' deliberately unmapped)
    ("pos", "completed", "COLLECTED"),
    ("pos", "pending", "PENDING"),
    ("pos", "failed", "FAILED"),
]


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# (source, source_id, raw_status, amount_minor, currency, occurred_at)
SYNTHETIC = [
    ("billing", "b1", "paid",     10000, "USD", "2026-07-01T10:00:00"),
    ("billing", "b2", "paid",      5000, "USD", "2026-07-02T11:00:00"),
    ("billing", "b3", "open",      3000, "USD", "2026-07-02T12:00:00"),  # pending
    ("billing", "b4", "refunded",  2000, "USD", "2026-07-03T09:00:00"),  # not collected
    ("billing", "b5", "paid",      8000, "EUR", "2026-07-03T15:00:00"),  # other currency
    ("pos",     "p1", "completed", 2500, "USD", "2026-07-01T18:00:00"),
    ("pos",     "p2", "completed", 7500, "USD", "2026-07-04T13:00:00"),
    ("pos",     "p3", "pending",   1000, "USD", "2026-07-04T14:00:00"),
    ("pos",     "p4", "failed",    4000, "USD", "2026-07-05T16:00:00"),
    ("pos",     "p5", "disputed",  9000, "USD", "2026-07-05T17:00:00"),  # UNMAPPED
]


def seed_status_map(conn) -> None:
    for source, raw, canon in STATUS_MAP:
        db.upsert_status_map(conn, source, raw, canon)
    conn.commit()


def seed_synthetic(conn) -> int:
    for source, sid, status, amt, cur, ts in SYNTHETIC:
        db.upsert_transaction(conn, source=source, source_id=sid, raw_status=status,
                              amount_minor=amt, currency=cur, occurred_at=_dt(ts),
                              raw={"seed": True})
    conn.commit()
    return len(SYNTHETIC)


def seed_stripe(conn) -> int:
    """Pull real test-mode PaymentIntents from Stripe and upsert them."""
    if not STRIPE_API_KEY:
        print("  (skipping stripe: STRIPE_API_KEY not set)")
        return 0
    import json
    import stripe
    stripe.api_key = STRIPE_API_KEY
    n = 0
    for pi in stripe.PaymentIntent.list(limit=100).auto_paging_iter():
        d = json.loads(str(pi))  # StripeObject isn't plainly dict()-able
        db.upsert_transaction(
            conn, source="stripe", source_id=d["id"], raw_status=d["status"],
            amount_minor=int(d["amount"]), currency=d["currency"],
            occurred_at=datetime.fromtimestamp(int(d["created"]), tz=timezone.utc),
            raw=d,
        )
        n += 1
    conn.commit()
    return n


def run() -> None:
    conn = db.connect()
    db.init_schema(conn)
    seed_status_map(conn)
    ns = seed_synthetic(conn)
    nstripe = seed_stripe(conn)
    print(f"seeded: status_map={len(STATUS_MAP)} synthetic_txns={ns} stripe_txns={nstripe}")
    unmapped = db.unmapped_statuses(conn)
    if unmapped:
        print("unmapped (excluded from revenue):", unmapped)
    conn.close()


if __name__ == "__main__":
    run()
