"""Structural guard: revenue may be summed in exactly ONE place
(metrics/canonical.py). If someone adds a second computation anywhere else,
this test fails — that is the mechanism that keeps the number from drifting.

No database needed; this is a static scan.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CANONICAL = REPO / "metrics" / "canonical.py"

# Any summation of transaction money. The one legitimate occurrence lives in
# canonical.py; anywhere else is a divergent definition.
FORBIDDEN = re.compile(r"SUM\s*\(\s*amount_minor", re.IGNORECASE)

# Directories that are not our source.
SKIP_DIRS = {".venv", ".git", "__pycache__", "node_modules"}


def _source_files():
    for path in REPO.rglob("*"):
        if path.suffix not in (".py", ".sql"):
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path == CANONICAL:
            continue
        if path.name == Path(__file__).name:  # this test names the pattern itself
            continue
        yield path


def test_revenue_summed_in_exactly_one_place():
    offenders = []
    for path in _source_files():
        text = path.read_text(errors="ignore")
        if FORBIDDEN.search(text):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        "collected-revenue is summed outside metrics/canonical.py — a second, "
        f"potentially divergent definition was added in: {offenders}. "
        "Route it through canonical.collected_revenue() instead.")


def test_canonical_actually_has_the_definition():
    # Sanity: the one true place really does contain the summation.
    assert FORBIDDEN.search(CANONICAL.read_text()), \
        "the canonical summation disappeared from metrics/canonical.py"
