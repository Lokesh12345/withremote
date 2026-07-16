"""Stripe payments adapter (PaymentIntents, test mode).

Cursor = ISO timestamp derived from `created`. Stripe cursors don't expire, so
the stale-cursor path is exercised via the injectable fault.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..config import CONFIG
from ..models import (PAYMENT, STRIPE, Record, RecordValidationError,
                      SourceDownError, StaleCursorError)
from . import fixtures
from .base import Adapter, FetchResult


def _epoch_to_iso(epoch: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


class StripeAdapter(Adapter):
    source = STRIPE
    cursor_type = "timestamp:created"

    # -- normalization ------------------------------------------------------ #
    def normalize(self, raw: dict[str, Any]) -> Record:
        rid = raw.get("id")
        if not rid:
            raise RecordValidationError("stripe payment missing id")
        amount_minor = raw.get("amount")
        try:
            amount = round(int(amount_minor) / 100.0, 2) if amount_minor is not None else None
        except (TypeError, ValueError):
            raise RecordValidationError(f"stripe payment {rid}: bad amount {amount_minor!r}")
        ts = _epoch_to_iso(raw.get("created"))
        return Record(
            source=STRIPE,
            source_id=str(rid),
            type=PAYMENT,
            source_updated_at=ts,
            title=raw.get("description"),
            email=raw.get("receipt_email"),
            amount=amount,
            currency=(raw.get("currency") or "").upper() or None,
            status=raw.get("status"),
            occurred_at=ts,
            raw=raw,
        )

    # -- fetch -------------------------------------------------------------- #
    def fetch_incremental(self, cursor: Optional[str]) -> FetchResult:
        if self._wants("down"):
            raise SourceDownError("stripe: injected outage")
        if self._wants("stale-cursor") and cursor:
            raise StaleCursorError("stripe: injected stale cursor")
        if self.mode == "live":
            return self._live(cursor)
        return self._fake(incremental_since=cursor)

    def fetch_full(self) -> FetchResult:
        if self._wants("down"):
            raise SourceDownError("stripe: injected outage")
        if self.mode == "live":
            return self._live(None)
        return self._fake(incremental_since=None)

    # -- fake --------------------------------------------------------------- #
    def _fake(self, incremental_since: Optional[str]) -> FetchResult:
        rows = list(fixtures.STRIPE_PAYMENTS)
        if incremental_since:
            rows = [r for r in rows if (_epoch_to_iso(r.get("created")) or "") > incremental_since]
        if self._wants("garbage"):
            rows = rows + [fixtures.STRIPE_GARBAGE]
        cursor = max((_epoch_to_iso(r.get("created")) for r in fixtures.STRIPE_PAYMENTS),
                     default=incremental_since)
        return FetchResult(rows, cursor, self.cursor_type)

    # -- live --------------------------------------------------------------- #
    def _live(self, cursor: Optional[str]) -> FetchResult:
        if not CONFIG.stripe_api_key:
            raise SourceDownError("stripe: STRIPE_API_KEY not set")
        import stripe
        stripe.api_key = CONFIG.stripe_api_key
        params: dict[str, Any] = {"limit": 100}
        if cursor:
            # created is an epoch int; convert our ISO cursor back.
            dt = datetime.fromisoformat(cursor)
            params["created"] = {"gt": int(dt.timestamp())}
        rows: list[dict[str, Any]] = []
        import json
        try:
            for pi in stripe.PaymentIntent.list(**params).auto_paging_iter():
                # StripeObject is not plainly dict()-able; its str() is JSON.
                rows.append(json.loads(str(pi)))
        except stripe.error.APIConnectionError as e:  # type: ignore[attr-defined]
            raise SourceDownError(f"stripe: {e}") from e
        except stripe.error.StripeError as e:  # type: ignore[attr-defined]
            raise SourceDownError(f"stripe: {e}") from e
        cursor_out = max((_epoch_to_iso(r.get("created")) for r in rows), default=cursor)
        return FetchResult(rows, cursor_out, self.cursor_type)
