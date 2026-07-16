#!/usr/bin/env bash
# PROOF: one source down and one returning garbage does not stop the others
# from landing their data.
set -euo pipefail
cd "$(dirname "$0")/.."
export SYNC_DB_PATH="./demo_fault.db"
export SYNC_MODE="fake"
rm -f "$SYNC_DB_PATH" "$SYNC_DB_PATH-wal" "$SYNC_DB_PATH-shm"

echo "=== sync all: stripe is DOWN, hubspot returns GARBAGE, gcal is healthy ==="
python -m syncpipe.cli sync --source all --fake \
    --inject down:stripe --inject garbage:hubspot

echo
echo "=== verify the healthy sources still landed, bad record quarantined ==="
python - <<'PY'
import os, sqlite3
c = sqlite3.connect(os.environ["SYNC_DB_PATH"])
def count(src): return c.execute("SELECT COUNT(*) FROM records WHERE source=?", (src,)).fetchone()[0]
hub, stripe, gcal = count("hubspot"), count("stripe"), count("gcal")
dead = c.execute("SELECT COUNT(*) FROM dead_letter").fetchone()[0]
stripe_status = c.execute("SELECT status FROM run_log WHERE source='stripe' ORDER BY id DESC LIMIT 1").fetchone()[0]
print(f"hubspot={hub} (2 good, 1 garbage dead-lettered)  stripe={stripe} (down)  gcal={gcal} (healthy)")
print(f"dead_letter rows: {dead}   stripe run status: {stripe_status}")
assert hub == 2, hub          # good hubspot records still landed
assert gcal == 2, gcal        # healthy source unaffected
assert stripe == 0, stripe    # down source wrote nothing
assert dead == 1, dead        # garbage quarantined, not crashing the batch
assert stripe_status == "failed"
print("PASS: fault in one source isolated; the other two landed their data")
PY
