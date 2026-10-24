"""Test bootstrap — MUST be imported before any `app.*` module.

`app/config.py` and `app/database.py` read the environment and create the
database AT IMPORT TIME, so the environment has to be pinned first. This module:

  * points the database at a throwaway temp file (the real rental_agent.db is
    never opened, so no customer record can be touched by a test run),
  * clears every LLM API key so no provider is ever called over the network,
  * clears the Kapso API key so the background poller stays inert, while
    keeping the webhook secret so signature verification can be exercised,
  * makes the backend package importable.

Note: `python-dotenv.load_dotenv()` does NOT override variables that already
exist in os.environ, so anything set here wins over the project's `.env`.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _TESTS_DIR.parent / "backend"

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# A fresh database per interpreter run: nothing here can reach production data.
_DB_DIR = Path(tempfile.mkdtemp(prefix="rental-agent-tests-"))
_DB_PATH = _DB_DIR / "test_rental_agent.db"

os.environ.update(
    {
        # --- database (isolated) --- #
        "DATABASE_URL": f"sqlite:///{_DB_PATH.as_posix()}",
        # --- WhatsApp transport --- #
        # Empty key => kapso.configured is False => the lifespan poller makes no
        # HTTP call at all. The phone-number id is kept because parsing and
        # error-classification tests assert on real-shaped payloads.
        "KAPSO_API_KEY": "",
        "KAPSO_PHONE_NUMBER_ID": "1264848293386510",
        "KAPSO_WEBHOOK_SECRET": "test-webhook-secret",
        # --- loopback origins so the link path is never assumed reachable --- #
        "PUBLIC_BASE_URL": "http://localhost:8022",
        "MEDIA_PUBLIC_BASE_URL": "",
        # --- no LLM provider may ever be contacted from a test run --- #
        "CLEANAPIS_API_KEY": "",
        "MANIFEST_API_KEY": "",
        "APINEX_API_KEY": "",
        "APIQIK_API_KEY": "",
        "AXQUA_API_KEY": "",
        "AI_PROXY_URL": "",
        "AI_PROXY_TOKEN": "",
        # --- console stays open locally, exactly like development --- #
        "ADMIN_AUTH_REQUIRED": "0",
        "ADMIN_API_TOKEN": "",
        # --- admin login endpoint (test credentials, never the real ones) --- #
        "ADMIN_EMAIL": "car_rental@example.com",
        "ADMIN_PASSWORD": "test-admin-pass",
        # --- deterministic business rules for assertions --- #
        "RENTAL_CURRENCY": "₹",
        "RENTAL_DRIVER_FEE_PER_DAY": "800",
        "RENTAL_DELIVERY_FEE": "500",
        "RENTAL_MIN_LEAD_HOURS": "2",
        "RENTAL_MAX_BOOKING_DAYS": "60",
        "HANDOFF_AUTO_RESUME_MINUTES": "30",
    }
)

# Make the test database path available to tests that seed/reset data.
TEST_DB_PATH = _DB_PATH
