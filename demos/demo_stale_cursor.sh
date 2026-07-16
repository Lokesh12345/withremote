#!/usr/bin/env bash
# PROOF: when an incremental cursor is rejected, the pipeline falls back to a
# full backfill instead of losing data or crashing.
set -euo pipefail
cd "$(dirname "$0")/.."
export SYNC_DB_PATH="./demo_stale.db"
export SYNC_MODE="fake"
rm -f "$SYNC_DB_PATH" "$SYNC_DB_PATH-wal" "$SYNC_DB_PATH-shm"

echo "=== run 1: normal incremental sync for gcal (establishes a cursor) ==="
python -m syncpipe.cli sync --source gcal --fake
python -m syncpipe.cli status | grep -A2 "sync_state"

echo
echo "=== run 2: cursor is now stale — inject a 410-style rejection ==="
echo "    expect mode = full_backfill_fallback, and all rows still present"
python -m syncpipe.cli sync --source gcal --fake --inject stale-cursor:gcal

echo
echo "=== verify no data was lost ==="
python - <<'PY'
import os, sqlite3
c = sqlite3.connect(os.environ["SYNC_DB_PATH"])
n = c.execute("SELECT COUNT(*) FROM records WHERE source='gcal'").fetchone()[0]
mode = c.execute("SELECT mode FROM run_log WHERE source='gcal' ORDER BY id DESC LIMIT 1").fetchone()[0]
print(f"gcal records: {n}, last run mode: {mode}")
assert n == 2, f"expected 2 gcal events, got {n}"
assert mode == "full_backfill_fallback", f"expected fallback, got {mode}"
print("PASS: stale cursor recovered via full backfill, zero data loss")
PY
