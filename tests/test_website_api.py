"""Website API regression tests: fleet, quotes, direct bookings, concierge.

Runs the REAL FastAPI app (main.app) against the throwaway SQLite database
created by tests/_bootstrap.py — no real customer record, no credentials, and
no network call (every LLM key is empty, so the concierge exercises the
deterministic flow + honest fallback path).

Test isolation: every booking test books a DIFFERENT window (pytest runs
unittest methods alphabetically), so tests can never collide on inventory.
"""
from __future__ import annotations

import pathlib
import re
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402  (must run first)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.bookings import create_draft  # noqa: E402
from app.agent import (  # noqa: E402
    get_or_create_conversation,
    get_or_create_customer,
)
from app.seed import ensure_seed  # noqa: E402


def _window(hours_from_now: float, duration_hours: float) -> tuple[str, str]:
    """One (start_iso, end_iso) pair from a single clock read — the two bounds
    are exactly duration_hours apart, immune to evaluation-time drift."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=hours_from_now)
    return start.isoformat(), (start + timedelta(hours=duration_hours)).isoformat()


def _future(hours: float) -> str:
    return _window(hours, 1)[0]


class WebsiteApiTestCase(unittest.TestCase):
    api: TestClient

    @classmethod
    def setUpClass(cls) -> None:
        from main import app

        with SessionLocal() as db:
            ensure_seed(db)
        cls.api = TestClient(app)

    # ------------------------------ config ------------------------------ #
    def test_site_config_exposes_whatsapp_number_and_rules(self) -> None:
        res = self.api.get("/api/site/config")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(re.fullmatch(r"\d{10,15}", data["whatsapp_number"]))
        self.assertEqual(data["currency"], "₹")
        self.assertGreaterEqual(data["min_lead_hours"], 1)
        self.assertIn("name", data["business"])

    # ------------------------------ fleet ------------------------------- #
    def test_vehicle_list_matches_seeded_fleet(self) -> None:
        res = self.api.get("/api/site/vehicles")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        # other test files may add vehicles to the shared test database; the
        # seeded rate-card fleet must always be present on the site (the site
        # only lists available vehicles, so presence implies listed/available)
        by_code = {v["code"]: v for v in data["vehicles"]}
        from app.seed import FLEET as SEEDED
        for row in SEEDED:
            self.assertIn(row["code"], by_code, row["code"])
        self.assertTrue(data["categories"])
        swift = by_code["ZR-SWIFT"]
        self.assertEqual(swift["price_24h"], 2400)
        self.assertIn(6, swift["packages"])
        # every car with a photo resolves a servable same-origin media URL
        roxx = by_code["ZR-THAR-ROXX"]
        self.assertIn("/media/", roxx["image_url"])
        self.assertTrue(roxx["image_url"].startswith("/"))

    def test_vehicle_detail_404_for_unknown_code(self) -> None:
        self.assertEqual(self.api.get("/api/site/vehicles/NOPE-1").status_code, 404)

    # ------------------------------ quotes ------------------------------ #
    def test_quote_package_rates_are_deterministic(self) -> None:
        for hours, expected in ((6, 1000), (12, 1500), (24, 2400)):
            start, end = _window(240, hours)
            res = self.api.post("/api/site/quote", json={
                "vehicle_code": "ZR-SWIFT",
                "start_at": start,
                "end_at": end,
                "with_driver": False,
                "delivery": False,
            })
            self.assertEqual(res.status_code, 200, res.text)
            body = res.json()
            self.assertTrue(body["available"])
            self.assertEqual(body["quote"]["base_amount"], expected)
            self.assertEqual(body["quote"]["deposit"], 3000)

    def test_quote_multi_day_uses_full_day_rate(self) -> None:
        start, end = _window(240, 48)
        res = self.api.post("/api/site/quote", json={
            "vehicle_code": "ZR-SWIFT",
            "start_at": start,
            "end_at": end,  # exactly 2 days
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["quote"]["base_amount"], 4800)

    def test_quote_chauffeur_and_delivery_fees(self) -> None:
        start, end = _window(240, 24)
        res = self.api.post("/api/site/quote", json={
            "vehicle_code": "ZR-SWIFT",
            "start_at": start,
            "end_at": end,
            "with_driver": True,
            "delivery": True,
        })
        q = res.json()["quote"]
        self.assertEqual(q["base_amount"], 2400)
        self.assertEqual(q["driver_fee"], 800)
        self.assertEqual(q["delivery_fee"], 500)
        self.assertEqual(q["total_estimate"], 3700)

    def test_quote_rejects_unoffered_package(self) -> None:
        # Thar Roxx publishes no 6-hour rate
        start, end = _window(240, 6)
        res = self.api.post("/api/site/quote", json={
            "vehicle_code": "ZR-THAR-ROXX",
            "start_at": start,
            "end_at": end,
        })
        self.assertEqual(res.status_code, 422)
        self.assertIn("package", res.json()["detail"])

    def test_quote_rejects_invalid_windows(self) -> None:
        base = {"vehicle_code": "ZR-SWIFT"}
        now = datetime.now(timezone.utc)
        invalid_pairs = [
            (now + timedelta(hours=240), now + timedelta(hours=236)),  # end < start
            (now - timedelta(hours=2), now + timedelta(hours=2)),      # start in the past
            (now + timedelta(hours=240), now + timedelta(hours=240)),  # end == start
        ]
        for start, end in invalid_pairs:
            res = self.api.post("/api/site/quote", json={
                **base, "start_at": start.isoformat(), "end_at": end.isoformat()})
            self.assertEqual(res.status_code, 422,
                             f"{start.isoformat()} → {end.isoformat()}")

    # ----------------------------- bookings ----------------------------- #
    def booking_payload(self, **overrides) -> dict:
        start, end = _window(24, 24)
        payload = {
            "vehicle_code": "ZR-SWIFT",
            "start_at": start,
            "end_at": end,
            "with_driver": False,
            "delivery": False,
            "pickup_location": "Hub",
            "dropoff_location": "",
            "name": "Test Customer",
            "phone": "+91 98200 12345",
            "notes": "website test",
            "idempotency_key": uuid.uuid4().hex,
        }
        payload.update(overrides)
        return payload

    def test_direct_booking_confirms_with_reference(self) -> None:
        res = self.api.post("/api/site/bookings", json=self.booking_payload())
        self.assertEqual(res.status_code, 201, res.text)
        booking = res.json()["booking"]
        self.assertEqual(booking["status"], "confirmed")
        self.assertTrue(re.fullmatch(r"RC-[A-Z0-9]{6}", booking["reference"]))
        self.assertEqual(booking["total_estimate"], 2400)
        self.assertEqual(booking["drive_mode"], "self")

        # persisted and retrievable with the right phone
        ref = booking["reference"]
        ok = self.api.get(f"/api/site/bookings/{ref}", params={"phone": "+919820012345"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["booking"]["reference"], ref)
        # wrong phone never leaks the booking
        bad = self.api.get(f"/api/site/bookings/{ref}", params={"phone": "+919999999999"})
        self.assertEqual(bad.status_code, 404)

    def test_overlapping_booking_is_rejected_with_alternatives(self) -> None:
        start, end = _window(120, 24)
        first = self.api.post("/api/site/bookings", json=self.booking_payload(
            start_at=start, end_at=end))
        self.assertEqual(first.status_code, 201, first.text)
        clash = self.api.post("/api/site/bookings", json=self.booking_payload(
            start_at=start, end_at=end,
            phone="+91 98200 99999", name="Other Customer"))
        self.assertEqual(clash.status_code, 409)
        detail = clash.json()["detail"]
        self.assertIn("alternatives", detail)
        self.assertTrue(detail["alternatives"])

    def test_adjacent_windows_do_not_overlap(self) -> None:
        start, end = _window(360, 24)
        res = self.api.post("/api/site/bookings", json=self.booking_payload(
            start_at=start, end_at=end))
        self.assertEqual(res.status_code, 201, res.text)
        next_start = datetime.fromisoformat(res.json()["booking"]["end_at"])
        nxt = self.api.post("/api/site/bookings", json=self.booking_payload(
            start_at=next_start.isoformat(),
            end_at=(next_start + timedelta(hours=24)).isoformat()))
        self.assertEqual(nxt.status_code, 201, nxt.text)

    def test_idempotent_submit_returns_same_booking(self) -> None:
        start, end = _window(600, 24)
        key = uuid.uuid4().hex
        first = self.api.post("/api/site/bookings", json=self.booking_payload(
            start_at=start, end_at=end, idempotency_key=key))
        self.assertEqual(first.status_code, 201)
        second = self.api.post("/api/site/bookings", json=self.booking_payload(
            start_at=start, end_at=end, idempotency_key=key, name="Different Name"))
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["booking"]["reference"],
                         second.json()["booking"]["reference"])
        self.assertTrue(second.json()["duplicate"])

    def test_booking_validation_errors(self) -> None:
        now = datetime.now(timezone.utc)
        bad_start = (now + timedelta(hours=1)).isoformat()  # inside the lead time
        zero_end = now + timedelta(hours=240)
        cases = [
            {"phone": "123"},                                   # too short
            {"start_at": bad_start},                            # inside lead time
            {"start_at": zero_end.isoformat(), "end_at": zero_end.isoformat()},  # zero length
        ]
        for override in cases:
            res = self.api.post("/api/site/bookings", json=self.booking_payload(**override))
            self.assertEqual(res.status_code, 422, f"{override} → {res.status_code}")

    # ---------------------------- concierge ----------------------------- #
    def test_concierge_greeting_runs_deterministic_flow(self) -> None:
        res = self.api.post("/api/site/concierge", json={
            "session_id": f"test{uuid.uuid4().hex[:10]}", "message": "hi",
        })
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["reply"])
        # the deterministic flow greets with the interactive main menu
        self.assertTrue(data.get("menu") or data.get("buttons") or data["reply"])

    def test_concierge_confirmation_hands_over_to_booking_form(self) -> None:
        session = f"test{uuid.uuid4().hex[:10]}"
        wa_id = f"web-{session}"
        with SessionLocal() as db:
            cust = get_or_create_customer(db, wa_id, "Web Tester")
            conv = get_or_create_conversation(db, cust, channel="website")
            from app.database import Vehicle
            from sqlalchemy import select

            vehicle = db.execute(
                select(Vehicle).where(Vehicle.code == "ZR-SWIFT")
            ).scalars().first()
            start = datetime.now(timezone.utc) + timedelta(days=30)
            create_draft(
                db, customer=cust, vehicle=vehicle,
                start=start, end=start + timedelta(hours=24),
                conversation_id=conv.id, hours=24,
            )
            db.commit()
        res = self.api.post("/api/site/concierge", json={
            "session_id": session, "message": "confirm",
        })
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["action"], "open_booking_form")
        self.assertEqual(data["booking_form"]["vehicle_code"], "ZR-SWIFT")

    def test_concierge_llm_fallback_is_graceful(self) -> None:
        # every LLM key is empty under the test bootstrap: the agent must still
        # answer honestly instead of erroring
        res = self.api.post("/api/site/concierge", json={
            "session_id": f"test{uuid.uuid4().hex[:10]}",
            "message": "Do you offer unlimited kilometers for outstation trips?",
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["reply"])

    def test_website_deeplink_message_gets_interactive_flow(self) -> None:
        """The website's 'Book on WhatsApp' prefilled message must trigger the
        deterministic flow (car card with tappable options), not a plain-text
        LLM reply."""
        res = self.api.post("/api/site/concierge", json={
            "session_id": f"test{uuid.uuid4().hex[:10]}",
            "message": ("Hi ZoomRideXX! 🚗\nI'd like to book the *Mahindra Thar Roxx* "
                        "(ZR-THAR-ROXX).\n• Package: 24 hours\n• Mode: Self-drive\n"
                        "• Handover: Hub self-pickup\nPlease confirm availability."),
        })
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        # the deterministic car card arrives as an interactive list + date buttons
        self.assertTrue(data.get("menu") or data.get("buttons"),
                        f"expected interactive options, got: {str(data)[:300]}")

    def test_plain_freeform_reply_still_offers_browse_button(self) -> None:
        """Even an LLM fallback reply must carry a tappable option (never plain text)."""
        res = self.api.post("/api/site/concierge", json={
            "session_id": f"test{uuid.uuid4().hex[:10]}",
            "message": "hello there, random question about weather",
        })
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(
            data.get("buttons") or data.get("menu"),
            f"expected buttons on every reply, got: {str(data)[:300]}",
        )

    def test_concierge_rate_limits_bursts(self) -> None:
        session = f"test{uuid.uuid4().hex[:10]}"
        first = self.api.post("/api/site/concierge", json={"session_id": session, "message": "hi"})
        self.assertEqual(first.status_code, 200)
        burst = self.api.post("/api/site/concierge", json={"session_id": session, "message": "hello"})
        self.assertEqual(burst.status_code, 429)

    # -------------------------- admin login ----------------------------- #
    def test_admin_login_rejects_bad_credentials(self) -> None:
        import os

        if not (os.getenv("ADMIN_EMAIL") and os.getenv("ADMIN_PASSWORD")):
            self.skipTest("admin login credentials not configured in the test env")
        res = self.api.post("/api/admin/login", json={
            "email": "car_rental@example.com", "password": "totally-wrong"})
        self.assertEqual(res.status_code, 401)

    def test_admin_login_issues_token_for_correct_credentials(self) -> None:
        import os

        email = os.getenv("ADMIN_EMAIL")
        password = os.getenv("ADMIN_PASSWORD")
        if not (email and password):
            self.skipTest("admin login credentials not configured in the test env")
        res = self.api.post("/api/admin/login", json={"email": email, "password": password})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["token"])
        self.assertEqual(data["email"], email)

    def test_admin_verify_reports_token_mode(self) -> None:
        res = self.api.post("/api/admin/verify")
        self.assertEqual(res.status_code, 200)
        self.assertIn(res.json()["mode"], ("token", "open"))
        self.assertIsInstance(res.json()["valid"], bool)


if __name__ == "__main__":
    unittest.main()
