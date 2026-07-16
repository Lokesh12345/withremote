"""HubSpot CRM contacts adapter.

Cursor = `lastmodifieddate` (ISO timestamp). HubSpot does not expire this kind
of cursor, so the stale-cursor path is exercised via the injectable fault.
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import CONFIG
from ..models import (CONTACT, HUBSPOT, Record, RecordValidationError,
                      SourceDownError, StaleCursorError)
from . import fixtures
from .base import Adapter, FetchResult


class HubSpotAdapter(Adapter):
    source = HUBSPOT
    cursor_type = "timestamp:lastmodifieddate"
    API = "https://api.hubapi.com"

    # -- normalization ------------------------------------------------------ #
    def normalize(self, raw: dict[str, Any]) -> Record:
        rid = raw.get("id")
        if not rid:
            raise RecordValidationError("hubspot contact missing id")
        props = raw.get("properties", {}) or {}
        name = " ".join(p for p in (props.get("firstname"), props.get("lastname")) if p)
        return Record(
            source=HUBSPOT,
            source_id=str(rid),
            type=CONTACT,
            source_updated_at=props.get("lastmodifieddate"),
            title=name or None,
            email=props.get("email"),
            status=props.get("lifecyclestage"),
            occurred_at=props.get("createdate"),
            raw=raw,
        )

    # -- fetch -------------------------------------------------------------- #
    def fetch_incremental(self, cursor: Optional[str]) -> FetchResult:
        if self._wants("down"):
            raise SourceDownError("hubspot: injected outage")
        # A real stale cursor would surface as an API error; simulate it here.
        if self._wants("stale-cursor") and cursor:
            raise StaleCursorError("hubspot: injected stale cursor")
        if self.mode == "live":
            return self._live_incremental(cursor)
        return self._fake(incremental_since=cursor)

    def fetch_full(self) -> FetchResult:
        if self._wants("down"):
            raise SourceDownError("hubspot: injected outage")
        if self.mode == "live":
            return self._live_full()
        return self._fake(incremental_since=None)

    # -- fake --------------------------------------------------------------- #
    def _fake(self, incremental_since: Optional[str]) -> FetchResult:
        rows = list(fixtures.HUBSPOT_CONTACTS)
        if incremental_since:
            rows = [r for r in rows
                    if (r["properties"].get("lastmodifieddate") or "") > incremental_since]
        if self._wants("garbage"):
            rows = rows + [fixtures.HUBSPOT_GARBAGE]
        cursor = max(
            (r["properties"].get("lastmodifieddate") for r in fixtures.HUBSPOT_CONTACTS),
            default=incremental_since,
        )
        return FetchResult(rows, cursor, self.cursor_type)

    # -- live --------------------------------------------------------------- #
    def _headers(self) -> dict[str, str]:
        if not CONFIG.hubspot_token:
            raise SourceDownError("hubspot: HUBSPOT_ACCESS_TOKEN not set")
        return {"Authorization": f"Bearer {CONFIG.hubspot_token}",
                "Content-Type": "application/json"}

    _PROPS = ["firstname", "lastname", "email", "lifecyclestage",
              "createdate", "lastmodifieddate"]

    def _live_incremental(self, cursor: Optional[str]) -> FetchResult:
        import requests
        if not cursor:
            return self._live_full()
        # Search for contacts modified since the cursor.
        body = {
            "filterGroups": [{"filters": [{
                "propertyName": "lastmodifieddate",
                "operator": "GT",
                "value": cursor,
            }]}],
            "properties": self._PROPS,
            "sorts": [{"propertyName": "lastmodifieddate", "direction": "ASCENDING"}],
            "limit": 100,
        }
        try:
            resp = requests.post(f"{self.API}/crm/v3/objects/contacts/search",
                                 headers=self._headers(), json=body, timeout=30)
        except requests.RequestException as e:
            raise SourceDownError(f"hubspot: {e}") from e
        if resp.status_code >= 500:
            raise SourceDownError(f"hubspot: {resp.status_code}")
        resp.raise_for_status()
        rows = resp.json().get("results", [])
        cursor_out = max((r["properties"].get("lastmodifieddate") for r in rows),
                         default=cursor)
        return FetchResult(rows, cursor_out, self.cursor_type)

    def _live_full(self) -> FetchResult:
        import requests
        rows: list[dict[str, Any]] = []
        after: Optional[str] = None
        try:
            while True:
                params: dict[str, Any] = {"limit": 100, "properties": ",".join(self._PROPS)}
                if after:
                    params["after"] = after
                resp = requests.get(f"{self.API}/crm/v3/objects/contacts",
                                    headers=self._headers(), params=params, timeout=30)
                if resp.status_code >= 500:
                    raise SourceDownError(f"hubspot: {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                rows.extend(data.get("results", []))
                after = data.get("paging", {}).get("next", {}).get("after")
                if not after:
                    break
        except requests.RequestException as e:
            raise SourceDownError(f"hubspot: {e}") from e
        cursor_out = max((r["properties"].get("lastmodifieddate") for r in rows),
                         default=None)
        return FetchResult(rows, cursor_out, self.cursor_type)
