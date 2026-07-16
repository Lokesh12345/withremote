"""Webhook receiver.

Every delivery funnels through the SAME normalize + idempotent-upsert path as
the poll job, and is additionally deduped on its delivery id — so a webhook
firing twice never produces a duplicate row.

Run with:
    uvicorn syncpipe.webhook:app --port 8000

Simplified contract for local testing (works in fake mode without secrets):
    POST /webhook/<source>
    { "delivery_id": "abc", "records": [ <native source payload>, ... ] }

Real providers are also handled: a Stripe Event body is unwrapped to its
data.object automatically.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Header, Request, Response

from . import db
from .adapters import build_adapter
from .config import CONFIG
from .models import RecordValidationError

app = FastAPI(title="syncpipe webhook receiver")

_VALID = {"hubspot", "stripe", "gcal"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _extract(source: str, payload: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    """Return (delivery_id, [native records]) for a source's webhook body."""
    # Simplified/local contract.
    if "records" in payload:
        return payload.get("delivery_id"), list(payload["records"])

    # Real Stripe event envelope.
    if source == "stripe" and payload.get("object") == "event":
        return payload.get("id"), [payload.get("data", {}).get("object", {})]

    # Real HubSpot delivers an array (handled below) — single object fallback.
    if "id" in payload:
        return str(payload["id"]), [payload]

    return None, []


@app.post("/webhook/{source}")
async def receive(source: str, request: Request,
                  stripe_signature: str | None = Header(default=None, alias="Stripe-Signature")
                  ) -> Response:
    if source not in _VALID:
        return Response(json.dumps({"error": "unknown source"}), status_code=404,
                        media_type="application/json")

    body = await request.body()

    # HubSpot posts a JSON array of events; normalize to a dict list.
    parsed = json.loads(body or b"{}")
    if isinstance(parsed, list):
        events = parsed
    else:
        events = [parsed]

    conn = db.connect()
    db.init_db(conn)
    adapter = build_adapter(source, mode=CONFIG.mode)

    processed, duplicates, dead = 0, 0, 0
    for payload in events:
        delivery_id, raws = _extract(source, payload)
        # Fall back to a content hash when the provider gives no delivery id,
        # so retries of the same content are still deduped.
        if not delivery_id:
            delivery_id = str(hash(json.dumps(payload, sort_keys=True, default=str)))

        if db.already_processed(conn, source, delivery_id):
            duplicates += 1
            conn.commit()
            continue

        for raw in raws:
            try:
                rec = adapter.normalize(raw)
            except RecordValidationError as e:
                db.dead_letter(conn, source, str(e), json.dumps(raw, default=str))
                dead += 1
                continue
            db.upsert_record(conn, rec)
            processed += 1
        conn.commit()

    return Response(
        json.dumps({"source": source, "processed": processed,
                    "duplicates": duplicates, "dead_lettered": dead}),
        media_type="application/json",
    )
