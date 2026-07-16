"""Shared fixtures. Ensures the Supabase schema + seed data exist once per run."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metrics import db, seed  # noqa: E402
from metrics.config import DATABASE_URL  # noqa: E402

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


@pytest.fixture(scope="session", autouse=True)
def _seeded():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    conn = db.connect()
    db.init_schema(conn)
    seed.seed_status_map(conn)
    seed.seed_synthetic(conn)
    seed.seed_stripe(conn)
    conn.close()


@pytest.fixture()
def conn():
    c = db.connect()
    yield c
    c.close()
