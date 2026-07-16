"""Environment-backed configuration. Loads `.env` once at import."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Config:
    db_path: str = _get("SYNC_DB_PATH", "./syncpipe.db")
    mode: str = _get("SYNC_MODE", "fake")  # "live" or "fake"

    # HubSpot
    hubspot_token: str = _get("HUBSPOT_ACCESS_TOKEN")
    hubspot_webhook_secret: str = _get("HUBSPOT_WEBHOOK_SECRET")

    # Stripe
    stripe_api_key: str = _get("STRIPE_API_KEY")
    stripe_webhook_secret: str = _get("STRIPE_WEBHOOK_SECRET")

    # Google Calendar
    google_calendar_id: str = _get("GOOGLE_CALENDAR_ID", "primary")
    google_credentials_file: str = _get("GOOGLE_CREDENTIALS_FILE", "./google_credentials.json")
    google_token_file: str = _get("GOOGLE_TOKEN_FILE", "./google_token.json")
    google_webhook_token: str = _get("GOOGLE_WEBHOOK_TOKEN")

    # Webhook receiver
    webhook_host: str = _get("WEBHOOK_HOST", "0.0.0.0")
    webhook_port: int = int(_get("WEBHOOK_PORT", "8000") or "8000")


CONFIG = Config()
