"""Fire the identical webhook twice and assert exactly one row results.

Uses FastAPI's in-process TestClient, so no server needs to be running.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SYNC_DB_PATH", "./demo_idempotency.db")
os.environ.setdefault("SYNC_MODE", "fake")

from fastapi.testclient import TestClient  # noqa: E402

from syncpipe.webhook import app  # noqa: E402

client = TestClient(app)

payload = {
    "delivery_id": "evt_webhook_123",
    "records": [{
        "id": "pi_777", "object": "payment_intent", "amount": 2500,
        "currency": "usd", "status": "succeeded",
        "receipt_email": "grace@example.com", "description": "Webhook payment",
        "created": 1752660000,
    }],
}

r1 = client.post("/webhook/stripe", json=payload)
print("first  delivery:", r1.json())
r2 = client.post("/webhook/stripe", json=payload)  # exact same delivery id
print("second delivery:", r2.json())

assert r2.json()["duplicates"] == 1, "second delivery should be flagged duplicate"

conn = sqlite3.connect(os.environ["SYNC_DB_PATH"])
n = conn.execute(
    "SELECT COUNT(*) FROM records WHERE source='stripe' AND source_id='pi_777'"
).fetchone()[0]
print(f"rows for pi_777 after two identical deliveries: {n}")
assert n == 1, f"expected exactly 1 row, got {n}"
print("PASS: double-fired webhook produced exactly one row")
