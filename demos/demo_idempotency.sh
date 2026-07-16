#!/usr/bin/env bash
# PROOF: re-running the sync and double-firing a webhook never duplicate rows.
set -euo pipefail
cd "$(dirname "$0")/.."
export SYNC_DB_PATH="./demo_idempotency.db"
export SYNC_MODE="fake"
rm -f "$SYNC_DB_PATH" "$SYNC_DB_PATH-wal" "$SYNC_DB_PATH-shm"

echo "=== run 1: initial sync (all sources, fake mode) ==="
python -m syncpipe.cli sync --source all --fake

echo
echo "=== run 2: identical re-run, back-to-back ==="
python -m syncpipe.cli sync --source all --fake

echo
echo "=== row count MUST be unchanged (upsert on natural key) ==="
python - <<'PY'
import os, sqlite3
c = sqlite3.connect(os.environ["SYNC_DB_PATH"])
n = c.execute("SELECT COUNT(*) FROM records").fetchone()[0]
print(f"total records after two full runs: {n}")
assert n == 6, f"expected 6 unique records, got {n}"
print("PASS: no duplicates from re-running the sync")
PY

echo
echo "=== webhook double-fire (same delivery id twice) ==="
python demos/webhook_double_fire.py
