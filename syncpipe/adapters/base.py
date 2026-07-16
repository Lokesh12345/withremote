"""Adapter interface shared by all sources."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..models import Record


@dataclass
class FetchResult:
    """A batch pulled from a source plus the cursor to persist for next time.

    `raw_records` are native, un-normalized payloads — the orchestrator calls
    `adapter.normalize()` on each so it can dead-letter individual bad records
    without losing the good ones in the batch.
    """

    raw_records: list[dict[str, Any]]
    cursor: Optional[str]
    cursor_type: str = ""


class Adapter:
    """Base class. Subclasses set `source`/`cursor_type` and implement the
    live fetch/normalize; fake behaviour is driven from fixtures here."""

    source: str = ""
    cursor_type: str = ""

    def __init__(self, mode: str = "fake", inject: Optional[set[str]] = None):
        self.mode = mode
        self.inject = inject or set()

    # -- fault helpers ------------------------------------------------------ #
    def _wants(self, fault: str) -> bool:
        return fault in self.inject

    # -- interface ---------------------------------------------------------- #
    def fetch_incremental(self, cursor: Optional[str]) -> FetchResult:
        raise NotImplementedError

    def fetch_full(self) -> FetchResult:
        raise NotImplementedError

    def normalize(self, raw: dict[str, Any]) -> Record:
        raise NotImplementedError
