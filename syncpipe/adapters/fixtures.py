"""Deterministic sample data in each source's *native* shape, used by fake
mode. Timestamps are fixed so demos are reproducible. A "garbage" record is
included per source (guarded by the `garbage` fault) to exercise dead-lettering.
"""
from __future__ import annotations

from typing import Any

# --- HubSpot contacts (as the CRM v3 API returns them) --------------------- #
HUBSPOT_CONTACTS: list[dict[str, Any]] = [
    {
        "id": "101",
        "properties": {
            "firstname": "Ada", "lastname": "Lovelace",
            "email": "ada@example.com", "lifecyclestage": "customer",
            "createdate": "2026-06-01T09:00:00Z",
            "lastmodifieddate": "2026-07-10T12:00:00Z",
        },
    },
    {
        "id": "102",
        "properties": {
            "firstname": "Alan", "lastname": "Turing",
            "email": "alan@example.com", "lifecyclestage": "lead",
            "createdate": "2026-06-05T09:00:00Z",
            "lastmodifieddate": "2026-07-11T08:30:00Z",
        },
    },
]

# A malformed contact — no id. Only served when the `garbage` fault is set.
HUBSPOT_GARBAGE: dict[str, Any] = {"properties": {"firstname": "No", "lastname": "Id"}}


# --- Stripe payment intents (native shape; amounts in minor units) --------- #
STRIPE_PAYMENTS: list[dict[str, Any]] = [
    {
        "id": "pi_001", "object": "payment_intent", "amount": 4999,
        "currency": "usd", "status": "succeeded", "receipt_email": "ada@example.com",
        "description": "Pro plan", "created": 1782903600,  # 2026-07-01T11:00:00Z
    },
    {
        "id": "pi_002", "object": "payment_intent", "amount": 1500,
        "currency": "eur", "status": "processing", "receipt_email": "alan@example.com",
        "description": "Add-on", "created": 1783591200,  # 2026-07-09T10:00:00Z
    },
]

STRIPE_GARBAGE: dict[str, Any] = {"object": "payment_intent", "amount": "not-a-number"}


# --- Google Calendar events (native v3 shape) ------------------------------ #
GCAL_EVENTS: list[dict[str, Any]] = [
    {
        "id": "evt_a", "status": "confirmed", "summary": "Kickoff call",
        "organizer": {"email": "ada@example.com"},
        "start": {"dateTime": "2026-07-15T15:00:00Z"},
        "end": {"dateTime": "2026-07-15T15:30:00Z"},
        "updated": "2026-07-12T09:00:00Z",
    },
    {
        "id": "evt_b", "status": "confirmed", "summary": "Design review",
        "organizer": {"email": "alan@example.com"},
        "start": {"dateTime": "2026-07-18T13:00:00Z"},
        "end": {"dateTime": "2026-07-18T14:00:00Z"},
        "updated": "2026-07-13T16:45:00Z",
    },
]

GCAL_GARBAGE: dict[str, Any] = {"status": "confirmed", "summary": "No id event"}
