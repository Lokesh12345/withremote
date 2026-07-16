"""syncpipe — a resilient multi-source sync pipeline.

Ingests records from HubSpot (CRM), Stripe (payments) and Google Calendar
(events) into one normalized SQLite schema. Handles stale cursors with a
full-backfill fallback, writes idempotently, and isolates per-source faults.
"""

__version__ = "0.1.0"
