"""Unified record shape and typed errors shared across adapters."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

# Canonical source identifiers.
HUBSPOT = "hubspot"
STRIPE = "stripe"
GCAL = "gcal"

# Canonical record types.
CONTACT = "contact"
PAYMENT = "payment"
EVENT = "event"


@dataclass
class Record:
    """One normalized record. The `(source, source_id)` pair is the natural
    key that makes every write idempotent."""

    source: str
    source_id: str
    type: str
    # ISO-8601 UTC string. Used for last-write-wins conflict resolution.
    source_updated_at: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    occurred_at: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def raw_json(self) -> str:
        return json.dumps(self.raw, sort_keys=True, default=str)


class AdapterError(Exception):
    """Base for all adapter-raised failures."""


class StaleCursorError(AdapterError):
    """Raised when a source rejects an incremental cursor (e.g. GCal 410 Gone,
    an expired sync/page token). Signals the orchestrator to fall back to a
    full backfill."""


class SourceDownError(AdapterError):
    """Raised when a source is unreachable or returns a 5xx. Confined to that
    source so the run continues with the others."""


class RecordValidationError(AdapterError):
    """Raised for an individual malformed record. The record is dead-lettered
    rather than crashing the batch."""
