"""Config for the metrics service. Normalizes DATABASE_URL so a raw '@' (or
other reserved char) in the password still parses."""
from __future__ import annotations

import os
import urllib.parse as up

from dotenv import load_dotenv

load_dotenv()


def normalize_db_url(url: str) -> str:
    """URL-encode the password component so an unescaped '@'/':' in it doesn't
    corrupt parsing. Idempotent: an already-encoded password is left intact."""
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return url
    userpass, host = rest.rsplit("@", 1)  # split on the LAST '@' = the real one
    if ":" not in userpass:
        return url
    user, passwd = userpass.split(":", 1)
    # unquote-then-quote makes it idempotent (%40 stays %40, raw @ becomes %40).
    enc = up.quote(up.unquote(passwd), safe="")
    return f"{scheme}://{user}:{enc}@{host}"


DATABASE_URL = normalize_db_url(os.environ.get("DATABASE_URL", "").strip())
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "").strip()
METRICS_HOST = os.environ.get("METRICS_HOST", "0.0.0.0").strip()
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8100") or "8100")
