"""Source adapters. Each adapter knows how to fetch (incremental + full) and
how to normalize its native record shape into the unified `Record`."""
from __future__ import annotations

from typing import Optional

from .base import Adapter, FetchResult
from .gcal import GCalAdapter
from .hubspot import HubSpotAdapter
from .stripe import StripeAdapter

_REGISTRY = {
    "hubspot": HubSpotAdapter,
    "stripe": StripeAdapter,
    "gcal": GCalAdapter,
}

ALL_SOURCES = list(_REGISTRY.keys())


def build_adapter(source: str, mode: str, inject: Optional[set[str]] = None) -> Adapter:
    try:
        cls = _REGISTRY[source]
    except KeyError:
        raise ValueError(f"unknown source: {source!r} (known: {ALL_SOURCES})")
    return cls(mode=mode, inject=inject or set())


__all__ = ["Adapter", "FetchResult", "build_adapter", "ALL_SOURCES"]
