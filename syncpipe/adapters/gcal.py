"""Google Calendar events adapter.

Cursor = `syncToken`. This is the one source where a stale cursor is REAL:
Google returns HTTP 410 Gone when a syncToken has expired, at which point the
documented recovery is a full resync. That 410 is mapped to StaleCursorError.
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import CONFIG
from ..models import (EVENT, GCAL, Record, RecordValidationError,
                      SourceDownError, StaleCursorError)
from . import fixtures
from .base import Adapter, FetchResult


class GCalAdapter(Adapter):
    source = GCAL
    cursor_type = "sync_token"

    # -- normalization ------------------------------------------------------ #
    def normalize(self, raw: dict[str, Any]) -> Record:
        rid = raw.get("id")
        if not rid:
            raise RecordValidationError("gcal event missing id")
        start = raw.get("start", {}) or {}
        occurred = start.get("dateTime") or start.get("date")
        organizer = raw.get("organizer", {}) or {}
        return Record(
            source=GCAL,
            source_id=str(rid),
            type=EVENT,
            source_updated_at=raw.get("updated"),
            title=raw.get("summary"),
            email=organizer.get("email"),
            status=raw.get("status"),
            occurred_at=occurred,
            raw=raw,
        )

    # -- fetch -------------------------------------------------------------- #
    def fetch_incremental(self, cursor: Optional[str]) -> FetchResult:
        if self._wants("down"):
            raise SourceDownError("gcal: injected outage")
        if self._wants("stale-cursor") and cursor:
            raise StaleCursorError("gcal: injected stale sync token (410)")
        if self.mode == "live":
            return self._live(cursor)
        return self._fake(sync_token=cursor)

    def fetch_full(self) -> FetchResult:
        if self._wants("down"):
            raise SourceDownError("gcal: injected outage")
        if self.mode == "live":
            return self._live(None)
        return self._fake(sync_token=None)

    # -- fake --------------------------------------------------------------- #
    # In fake mode the sync token encodes the last-seen `updated` watermark.
    def _fake(self, sync_token: Optional[str]) -> FetchResult:
        rows = list(fixtures.GCAL_EVENTS)
        watermark = sync_token[len("tok:"):] if sync_token and sync_token.startswith("tok:") else None
        if watermark:
            rows = [r for r in rows if (r.get("updated") or "") > watermark]
        if self._wants("garbage"):
            rows = rows + [fixtures.GCAL_GARBAGE]
        newest = max((r.get("updated") for r in fixtures.GCAL_EVENTS), default=watermark)
        token = f"tok:{newest}" if newest else sync_token
        return FetchResult(rows, token, self.cursor_type)

    # -- live --------------------------------------------------------------- #
    def _service(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as e:
            raise SourceDownError(f"gcal: google libraries not installed ({e})") from e

        import os
        scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
        creds = None
        if os.path.exists(CONFIG.google_token_file):
            creds = Credentials.from_authorized_user_file(CONFIG.google_token_file, scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CONFIG.google_credentials_file, scopes)
                creds = flow.run_local_server(port=0)
            with open(CONFIG.google_token_file, "w") as fh:
                fh.write(creds.to_json())
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def _live(self, sync_token: Optional[str]) -> FetchResult:
        from googleapiclient.errors import HttpError
        service = self._service()
        rows: list[dict[str, Any]] = []
        page_token: Optional[str] = None
        next_sync: Optional[str] = None
        try:
            while True:
                params: dict[str, Any] = {"calendarId": CONFIG.google_calendar_id,
                                          "singleEvents": True, "maxResults": 250}
                if sync_token:
                    params["syncToken"] = sync_token
                if page_token:
                    params["pageToken"] = page_token
                resp = service.events().list(**params).execute()
                rows.extend(resp.get("items", []))
                page_token = resp.get("nextPageToken")
                next_sync = resp.get("nextSyncToken") or next_sync
                if not page_token:
                    break
        except HttpError as e:
            if getattr(e, "resp", None) is not None and e.resp.status == 410:
                # Sync token expired — caller falls back to a full backfill.
                raise StaleCursorError("gcal: 410 Gone (expired syncToken)") from e
            if getattr(e, "resp", None) is not None and e.resp.status >= 500:
                raise SourceDownError(f"gcal: {e.resp.status}") from e
            raise
        return FetchResult(rows, next_sync or sync_token, self.cursor_type)
