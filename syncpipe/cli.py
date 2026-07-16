"""Command-line entry point.

Examples:
    python -m syncpipe.cli init-db
    python -m syncpipe.cli sync --source all
    python -m syncpipe.cli sync --source gcal --inject stale-cursor:gcal
    python -m syncpipe.cli sync --source all --inject down:stripe --inject garbage:hubspot
    python -m syncpipe.cli status
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from . import db
from .adapters import ALL_SOURCES
from .config import CONFIG
from .orchestrator import RunSummary, run_sync


def _parse_inject(items: list[str]) -> dict[str, set[str]]:
    """`--inject fault:source` -> {source: {fault}}."""
    out: dict[str, set[str]] = defaultdict(set)
    for item in items or []:
        if ":" not in item:
            raise SystemExit(f"bad --inject value {item!r}; expected fault:source")
        fault, source = item.split(":", 1)
        out[source].add(fault)
    return dict(out)


def _print_summary(summary: RunSummary) -> None:
    print(f"\nrun {summary.run_id}")
    header = f"{'source':10} {'mode':22} {'fetch':>6} {'ins':>4} {'upd':>4} {'skip':>4} {'dead':>4} {'status':>8}"
    print(header)
    print("-" * len(header))
    for r in summary.results:
        print(f"{r.source:10} {r.mode:22} {r.fetched:>6} {r.inserted:>4} "
              f"{r.updated:>4} {r.skipped:>4} {r.dead_lettered:>4} {r.status:>8}")
        if r.error:
            print(f"           └─ {r.error}")
    print(f"\noverall: {'OK' if summary.ok else 'DEGRADED (some sources failed)'}")


def cmd_init_db(args: argparse.Namespace) -> int:
    conn = db.connect()
    db.init_db(conn)
    print(f"initialized {CONFIG.db_path}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    conn = db.connect()
    db.init_db(conn)
    sources = ALL_SOURCES if args.source == "all" else [args.source]
    mode = "live" if args.live else ("fake" if args.fake else CONFIG.mode)
    summary = run_sync(conn, sources, mode=mode, fetch_mode=args.mode,
                       inject_map=_parse_inject(args.inject))
    _print_summary(summary)
    # Exit non-zero only if EVERY source failed; partial success is still a
    # successful run by design (fault isolation).
    return 0 if any(r.status == "ok" for r in summary.results) else 1


def cmd_status(args: argparse.Namespace) -> int:
    conn = db.connect()
    db.init_db(conn)
    print("records by source:")
    for row in conn.execute(
        "SELECT source, type, COUNT(*) n FROM records GROUP BY source, type ORDER BY source"
    ):
        print(f"  {row['source']:10} {row['type']:10} {row['n']}")

    print("\nsync_state (cursors):")
    for row in conn.execute("SELECT * FROM sync_state ORDER BY source"):
        print(f"  {row['source']:10} cursor={row['cursor']!r} "
              f"type={row['cursor_type']} last_success={row['last_success_at']}")

    dead = conn.execute("SELECT COUNT(*) n FROM dead_letter").fetchone()["n"]
    print(f"\ndead_letter rows: {dead}")

    print("\nrecent runs:")
    for row in conn.execute(
        "SELECT run_id, source, mode, upserted, dead_lettered, status "
        "FROM run_log ORDER BY id DESC LIMIT 12"
    ):
        print(f"  {row['run_id']} {row['source']:10} {row['mode']:22} "
              f"upserted={row['upserted']} dead={row['dead_lettered']} {row['status']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="syncpipe", description="resilient multi-source sync pipeline")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the SQLite schema").set_defaults(func=cmd_init_db)

    s = sub.add_parser("sync", help="run a sync")
    s.add_argument("--source", default="all", choices=["all", *ALL_SOURCES])
    s.add_argument("--mode", default="incremental", choices=["incremental", "full"])
    s.add_argument("--fake", action="store_true", help="force fake mode (fixtures)")
    s.add_argument("--live", action="store_true", help="force live mode (real APIs)")
    s.add_argument("--inject", action="append", default=[],
                   metavar="FAULT:SOURCE",
                   help="inject a fault, e.g. stale-cursor:gcal, down:stripe, garbage:hubspot")
    s.set_defaults(func=cmd_sync)

    sub.add_parser("status", help="show DB state").set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
