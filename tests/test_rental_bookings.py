"""Rental pricing, availability, bookings, cancellation and copy regressions.

Every test runs against a throwaway SQLite database created by
`tests/_bootstrap.py`; no real customer record, credential or network call is
involved. Money and availability assertions describe the deterministic booking
service (`app/bookings.py`) and fleet service (`app/vehicles.py`), which are the
only things allowed to decide a price or a free slot.
"""
from __future__ import annotations

import pathlib
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402  (must run first)

from app.bookings import (  # noqa: E402
    booking_summary,
    cancel,
    confirm_draft,
    create_draft,
    customer_bookings,
    draft_for,
    find_by_reference,
    quote,
    rental_days,
    validate_window,
)
from app.config import RENTAL_CURRENCY, RENTAL_DELIVERY_FEE, RENTAL_DRIVER_FEE_PER_DAY  # noqa: E402
from app.database import Booking, Customer, SessionLocal, Vehicle  # noqa: E402
from app.languages import detect_language, detect_language_request  # noqa: E402
from app.media import registry, resolve, save_upload, validate_image  # noqa: E402
from app.menu import (  # noqa: E402
    BROWSE_ALL_ID,
    CAR_PREFIX,
    CONFIRM_BOOKING_ID,
    DESK_NUMBERS,
    KYC_WHATSAPP_ID,
    MENU_BOOK_CAR_ID,
    NEXT_CAR_ID,
    PREV_CAR_ID,
    SHOP_NAME,
    car_card_text,
    car_carousel_body,
    car_row,
    money,
    rules_text,
)
from app.kapso import build_interactive_carousel_payload  # noqa: E402
from app.persona import CORE_PERSONA, PERSONA_FIELDS, get_persona  # noqa: E402
from app.vehicles import (  # noqa: E402
    alternatives,
    delete_vehicle,
    find_vehicle,
    is_free,
    offers_packages,
    package_price,
    search_vehicles,
    upsert_vehicle,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _at(days: int, hour: int = 10) -> datetime:
    """A future, aware UTC instant (well past the minimum lead time)."""
    base = (_now() + timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    return base.replace(hour=hour)


class RentalTestCase(unittest.TestCase):
    """Shared helpers: unique codes, one session per test."""

    def setUp(self) -> None:
        self.db = SessionLocal()
        self._tag = uuid.uuid4().hex[:8]

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()

    def code(self, prefix: str = "CAR") -> str:
        return f"{prefix}-{self._tag.upper()}-{uuid.uuid4().hex[:4].upper()}"

    def new_vehicle(self, *, available: int = 1, **overrides) -> Vehicle:
        fields = {
            "name": f"Test Vehicle {uuid.uuid4().hex[:4]}",
            "category": "SUV",
            "seats": 5,
            "transmission": "manual",
            "fuel": "diesel",
            "price_per_day": 2000.0,
            "deposit": 5000.0,
            "driver_fee_per_day": 800.0,
            "mileage_limit_per_day": 300.0,
            "extra_km_charge": 12.0,
            "location": "Main office",
        }
        fields.update(overrides)
        row = upsert_vehicle(self.db, code=self.code(), available=available, **fields)
        self.db.commit()
        return row

    def new_customer(self, name: str = "Test Customer") -> Customer:
        cust = Customer(
            phone=f"9199{uuid.uuid4().int % 10**8:08d}",
            display_phone="+9199...",
            whatsapp_name=name,
        )
        self.db.add(cust)
        self.db.commit()
        return cust

    def conversation_id(self) -> str:
        return f"conv-{uuid.uuid4().hex}"

    def book(self, vehicle: Vehicle, start: datetime, end: datetime):
        """Create and CONFIRM a reservation (the only way to block a vehicle)."""
        cust = self.new_customer()
        conv = self.conversation_id()
        draft = create_draft(self.db, customer=cust, vehicle=vehicle, start=start,
                             end=end, conversation_id=conv)
        self.db.commit()
        booking, reason = confirm_draft(
            self.db, draft=draft,
            confirming_message_id=f"wamid.{uuid.uuid4().hex}",
        )
        self.assertEqual(reason, "", f"setup booking failed: {reason}")
        return booking


class PricingTests(RentalTestCase):
    def test_rental_days_counts_any_started_day(self) -> None:
        start = _at(3)
        self.assertEqual(rental_days(start, start + timedelta(hours=1)), 1)
        self.assertEqual(rental_days(start, start + timedelta(hours=24)), 1)
        self.assertEqual(rental_days(start, start + timedelta(hours=24, seconds=1)), 2)

    def test_day_quote_breakdown(self) -> None:
        vehicle = self.new_vehicle()
        start, end = _at(3), _at(5)
        q = quote(vehicle, start, end)
        self.assertEqual(q["days"], 2)
        self.assertEqual(q["base_amount"], 4000.0)
        self.assertEqual(q["total_estimate"], 4000.0)
        self.assertEqual(q["currency"], RENTAL_CURRENCY)
        self.assertEqual(q["deposit"], 5000.0)
        self.assertNotIn(q["deposit"], [q["total_estimate"]])

    def test_package_price_wins_over_the_day_rate(self) -> None:
        vehicle = self.new_vehicle(price_6h=1000.0, price_12h=1500.0, price_24h=2400.0)
        self.assertEqual(package_price(vehicle, 6), 1000.0)
        self.assertEqual(offers_packages(vehicle), [6, 12, 24])
        q = quote(vehicle, _at(3), _at(3, 12), hours=6)
        self.assertEqual(q["duration_hours"], 6)
        self.assertEqual(q["base_amount"], 1000.0)

    def test_chauffeur_and_delivery_are_added_when_requested(self) -> None:
        vehicle = self.new_vehicle()
        q = quote(vehicle, _at(3), _at(5), with_driver=True, delivery=True)
        self.assertEqual(q["driver_fee"], 2 * 800.0)
        self.assertEqual(q["delivery_fee"], RENTAL_DELIVERY_FEE)
        self.assertEqual(
            q["total_estimate"],
            q["base_amount"] + q["driver_fee"] + q["delivery_fee"],
        )

    def test_driver_fee_default_is_used_when_the_vehicle_has_none(self) -> None:
        vehicle = self.new_vehicle(driver_fee_per_day=None)
        q = quote(vehicle, _at(3), _at(4), with_driver=True)
        self.assertEqual(q["driver_fee"], RENTAL_DRIVER_FEE_PER_DAY)


class WindowValidationTests(RentalTestCase):
    def test_valid_window_is_accepted(self) -> None:
        self.assertEqual(validate_window(_at(3), _at(5)), "")

    def test_missing_times_are_rejected(self) -> None:
        self.assertIn("required", validate_window(None, _at(5)))
        self.assertIn("required", validate_window(_at(3), None))

    def test_return_before_pickup_is_rejected(self) -> None:
        self.assertIn("after", validate_window(_at(5), _at(3)))

    def test_past_pickup_is_rejected(self) -> None:
        self.assertIn("past", validate_window(_now() - timedelta(days=1), _at(1)))

    def test_insufficient_lead_time_is_rejected(self) -> None:
        soon = _now() + timedelta(minutes=5)
        self.assertIn("preparation", validate_window(soon, soon + timedelta(days=1)))


class AvailabilityTests(RentalTestCase):
    def test_a_confirmed_booking_blocks_an_overlapping_window(self) -> None:
        vehicle = self.new_vehicle()
        self.book(vehicle, _at(3, 10), _at(3, 12))
        self.assertFalse(is_free(self.db, vehicle.id, _at(3, 11), _at(3, 13)))

    def test_touching_windows_do_not_overlap(self) -> None:
        vehicle = self.new_vehicle()
        self.book(vehicle, _at(3, 10), _at(3, 12))
        self.assertTrue(is_free(self.db, vehicle.id, _at(3, 12), _at(3, 14)))
        self.assertTrue(is_free(self.db, vehicle.id, _at(3, 8), _at(3, 10)))

    def test_a_draft_never_blocks_the_vehicle(self) -> None:
        vehicle = self.new_vehicle()
        create_draft(self.db, customer=self.new_customer(), vehicle=vehicle,
                     start=_at(4, 10), end=_at(4, 12),
                     conversation_id=self.conversation_id())
        self.db.commit()
        self.assertTrue(is_free(self.db, vehicle.id, _at(4, 10), _at(4, 12)))

    def test_two_customers_cannot_hold_one_vehicle(self) -> None:
        vehicle = self.new_vehicle()
        self.book(vehicle, _at(6, 9), _at(6, 18))
        draft = create_draft(self.db, customer=self.new_customer("Second"),
                             vehicle=vehicle, start=_at(6, 12), end=_at(6, 20),
                             conversation_id=self.conversation_id())
        self.db.commit()
        booking, reason = confirm_draft(self.db, draft=draft,
                                        confirming_message_id="wamid.clash")
        self.assertIsNone(booking)
        self.assertIn("booked", reason)

    def test_alternatives_only_offer_available_vehicles(self) -> None:
        category = f"SUV {self._tag}"
        taken = self.new_vehicle(category=category)
        free_one = self.new_vehicle(category=category, price_per_day=2500.0)
        parked = self.new_vehicle(available=0, category=category)
        self.book(taken, _at(7, 9), _at(7, 18))
        rows = alternatives(self.db, _at(7, 9), _at(7, 18), category=category,
                            exclude_vehicle_id=taken.id)
        ids = {v.id for v in rows}
        self.assertIn(free_one.id, ids)
        self.assertNotIn(taken.id, ids)
        self.assertNotIn(parked.id, ids)

    def test_parked_vehicles_are_not_searchable(self) -> None:
        parked = self.new_vehicle(available=0, name="ZzParkedUnicorn")
        self.assertIsNone(find_vehicle(self.db, parked.code))
        self.assertNotIn(parked.id, {v.id for v in search_vehicles(self.db, "ZzParkedUnicorn")})


class ReservationTests(RentalTestCase):
    def test_confirmed_booking_gets_a_unique_reference(self) -> None:
        booking = self.book(self.new_vehicle(), _at(3, 10), _at(4, 10))
        self.assertEqual(booking.status, "confirmed")
        self.assertRegex(booking.reference, r"^RC-[A-Z0-9]{6}$")
        self.assertIsNotNone(booking.confirmed_at)

    def test_replayed_confirmation_creates_only_one_booking(self) -> None:
        vehicle = self.new_vehicle()
        draft = create_draft(self.db, customer=self.new_customer(), vehicle=vehicle,
                             start=_at(3, 10), end=_at(4, 10),
                             conversation_id=self.conversation_id())
        self.db.commit()
        first, reason = confirm_draft(self.db, draft=draft,
                                      confirming_message_id="wamid.same-tap")
        self.assertEqual(reason, "")
        second, reason2 = confirm_draft(self.db, draft=draft,
                                        confirming_message_id="wamid.same-tap")
        self.assertEqual(reason2, "")
        self.assertEqual(first.reference, second.reference)
        count = self.db.query(Booking).filter(Booking.reference == first.reference).count()
        self.assertEqual(count, 1)

    def test_a_withdrawn_vehicle_cannot_be_confirmed(self) -> None:
        vehicle = self.new_vehicle()
        draft = create_draft(self.db, customer=self.new_customer(), vehicle=vehicle,
                             start=_at(3, 10), end=_at(4, 10),
                             conversation_id=self.conversation_id())
        self.db.commit()
        vehicle.available = 0
        self.db.commit()
        booking, reason = confirm_draft(self.db, draft=draft,
                                        confirming_message_id="wamid.withdrawn")
        self.assertIsNone(booking)
        self.assertIn("no longer available", reason)

    def test_booking_summary_is_customer_readable(self) -> None:
        vehicle = self.new_vehicle()
        booking = self.book(vehicle, _at(3, 10), _at(5, 10))
        summary = booking_summary(booking, vehicle)
        self.assertIn(booking.reference, summary)
        self.assertIn(vehicle.name, summary)


class OwnershipTests(RentalTestCase):
    def test_reference_lookup_is_scoped_to_the_owner(self) -> None:
        booking = self.book(self.new_vehicle(), _at(3, 10), _at(4, 10))
        owner = self.db.get(Customer, booking.customer_id)
        self.assertIsNotNone(find_by_reference(self.db, owner.id, booking.reference))
        stranger = self.new_customer("Stranger")
        self.assertIsNone(find_by_reference(self.db, stranger.id, booking.reference))

    def test_my_bookings_lists_only_my_rows(self) -> None:
        mine = self.book(self.new_vehicle(), _at(3, 10), _at(4, 10))
        theirs = self.book(self.new_vehicle(), _at(3, 10), _at(4, 10))
        rows = customer_bookings(self.db, mine.customer_id)
        self.assertEqual([b.id for b in rows], [mine.id])
        self.assertNotIn(theirs.id, [b.id for b in rows])

    def test_customer_can_cancel_before_pickup(self) -> None:
        booking = self.book(self.new_vehicle(), _at(3, 10), _at(4, 10))
        ok, reason = cancel(self.db, booking, by_customer=True)
        self.assertTrue(ok, reason)
        self.assertEqual(booking.status, "cancelled")

    def test_customer_cannot_cancel_once_started(self) -> None:
        booking = self.book(self.new_vehicle(), _at(3, 10), _at(4, 10))
        booking.start_at = _now() - timedelta(hours=1)
        self.db.commit()
        ok, reason = cancel(self.db, booking, by_customer=True)
        self.assertFalse(ok)
        self.assertIn("staff", reason)

    def test_a_cancelled_booking_frees_the_vehicle(self) -> None:
        vehicle = self.new_vehicle()
        booking = self.book(vehicle, _at(3, 10), _at(4, 10))
        self.assertFalse(is_free(self.db, vehicle.id, _at(3, 11), _at(3, 13)))
        cancel(self.db, booking, by_customer=True)
        self.assertTrue(is_free(self.db, vehicle.id, _at(3, 11), _at(3, 13)))

    def test_draft_cannot_be_cancelled(self) -> None:
        draft = create_draft(self.db, customer=self.new_customer(),
                             vehicle=self.new_vehicle(),
                             start=_at(3, 10), end=_at(4, 10),
                             conversation_id=self.conversation_id())
        self.db.commit()
        ok, reason = cancel(self.db, draft, by_customer=True)
        self.assertFalse(ok)
        self.assertIn("confirmed", reason)


class FleetAdminTests(RentalTestCase):
    def test_a_booked_vehicle_cannot_be_deleted(self) -> None:
        vehicle = self.new_vehicle()
        self.book(vehicle, _at(3, 10), _at(4, 10))
        with self.assertRaises(ValueError):
            delete_vehicle(self.db, vehicle.code)

    def test_an_unbooked_vehicle_can_be_deleted(self) -> None:
        vehicle = self.new_vehicle()
        self.assertTrue(delete_vehicle(self.db, vehicle.code))
        self.db.commit()
        self.assertIsNone(find_vehicle(self.db, vehicle.code, include_unavailable=True))

    def test_draft_lookup_never_returns_another_conversation(self) -> None:
        create_draft(self.db, customer=self.new_customer(), vehicle=self.new_vehicle(),
                     start=_at(3, 10), end=_at(4, 10),
                     conversation_id="conv-owned-by-someone-else")
        self.db.commit()
        self.assertIsNone(draft_for(self.db, "conv-a-different-chat"))
        self.assertIsNone(draft_for(self.db, ""))


class CopyTests(unittest.TestCase):
    def test_menu_copy_names_the_real_business(self) -> None:
        self.assertIn("ZoomRideXX", SHOP_NAME)
        self.assertEqual(DESK_NUMBERS[0], "+91 91796 42928")
        self.assertIn("91796", rules_text("en") + " ".join(DESK_NUMBERS))

    def test_car_card_shows_every_published_package(self) -> None:
        vehicle = Vehicle(code="T-1", name="Test Car", price_6h=1000.0,
                           price_12h=1500.0, price_24h=2400.0, deposit=3000.0)
        text = car_card_text(vehicle, "en")
        self.assertIn("6 hours", text)
        self.assertIn("12 hours", text)
        self.assertIn("24 hours", text)
        self.assertIn(money(2400), text)
        self.assertEqual(car_row(vehicle)["id"], CAR_PREFIX + "t-1")

    def test_booking_and_kyc_ids_are_stable(self) -> None:
        self.assertEqual(MENU_BOOK_CAR_ID, "menu_book_car")
        self.assertEqual(CONFIRM_BOOKING_ID, "confirm_booking")
        self.assertEqual(KYC_WHATSAPP_ID, "kyc_whatsapp")

    def test_carousel_ids_are_stable(self) -> None:
        self.assertEqual(BROWSE_ALL_ID, "browse_all_cars")
        self.assertEqual(PREV_CAR_ID, "prev_car")
        self.assertEqual(NEXT_CAR_ID, "next_car")

    def test_car_card_shows_carousel_position(self) -> None:
        vehicle = Vehicle(code="T-2", name="Test Car", price_6h=1000.0,
                          price_12h=1500.0, deposit=3000.0)
        text = car_card_text(vehicle, "en", position="Car 2 of 17")
        self.assertIn("Car 2 of 17", text)

    def test_carousel_card_body_fits_whatsapps_limits(self) -> None:
        vehicle = Vehicle(
            code="T-3", name="Hyundai Creta", category="Compact SUV",
            fuel="diesel", transmission="automatic", seats=5,
            price_6h=1200.0, price_12h=1800.0, price_24h=2700.0,
        )
        body = car_carousel_body(vehicle, "en")
        self.assertLessEqual(len(body), 160)
        self.assertEqual(body.count("\n"), 2)
        self.assertIn("Compact SUV", body)
        self.assertIn(money(1800), body)
        self.assertIn("24 hrs", body)

        six_hour = car_carousel_body(vehicle, "en", hours=6)
        self.assertLessEqual(len(six_hour), 160)
        self.assertEqual(six_hour.count("\n"), 2)
        self.assertTrue(six_hour.splitlines()[2].startswith(f"{money(1200)} / 6 hrs"))

    def test_carousel_payload_matches_whatsapp_shape(self) -> None:
        cards = [
            {
                "header": {"type": "image", "image": {"id": "media-1"}},
                "body_text": "Car One\nSUV · Diesel · Automatic · 5 seats\n₹3,500 / 12 hrs",
                "buttons": [("bookcar_ZR-1", "Book Now"), ("viewcar_ZR-1", "View Details")],
            },
            {
                "header": {"type": "image", "image": {"link": "https://example.com/2.jpg"}},
                "body_text": "Car Two\nSedan · Petrol · Manual · 5 seats\n₹1,500 / 12 hrs",
                "buttons": [("bookcar_ZR-2", "Book Now"), ("viewcar_ZR-2", "View Details")],
            },
        ]
        payload = build_interactive_carousel_payload("+91 90000 00000", "Browse our fleet", cards)
        self.assertEqual(payload["type"], "interactive")
        interactive = payload["interactive"]
        self.assertEqual(interactive["type"], "carousel")
        self.assertEqual(interactive["body"]["text"], "Browse our fleet")
        built = interactive["action"]["cards"]
        self.assertEqual([card["card_index"] for card in built], [0, 1])
        self.assertEqual(built[0]["type"], "cta_url")
        self.assertEqual(built[0]["action"]["buttons"][0]["type"], "quick_reply")
        self.assertEqual(built[0]["action"]["buttons"][0]["quick_reply"]["id"],
                         "bookcar_ZR-1")
        self.assertEqual(built[1]["header"]["image"]["link"],
                         "https://example.com/2.jpg")


class LanguageTests(unittest.TestCase):
    def test_detection_handles_english_and_hinglish(self) -> None:
        self.assertEqual(detect_language("What is the price of Creta?"), "en")
        self.assertEqual(detect_language("Mujhe Creta ka rent batao"), "hi")
        self.assertEqual(detect_language("किराया कितना है?"), "hi")

    def test_an_explicit_switch_request_is_detected(self) -> None:
        self.assertEqual(detect_language_request("speak in hindi"), "hi")
        self.assertEqual(detect_language_request("अब हिंदी में बात करो"), "hi")
        self.assertIsNone(detect_language_request("send me the Thar photo"))


class PersonaTests(RentalTestCase):
    def test_the_core_rental_role_is_always_in_the_prompt(self) -> None:
        self.assertIn(CORE_PERSONA, get_persona(self.db).as_prompt())

    def test_persona_defaults_have_no_sweet_shop_leftovers(self) -> None:
        joined = " ".join(spec["default"].lower() for spec in PERSONA_FIELDS.values())
        for word in ("sweet", "mithai", "kaju", "laddoo", "jewellery"):
            with self.subTest(word=word):
                self.assertNotIn(word, joined)


class MediaTests(unittest.TestCase):
    def test_registry_never_resolves_a_path_like_id(self) -> None:
        for hostile in ("../../etc/passwd", "/etc/passwd", "C:\\Windows\\win.ini",
                        "..\\..\\secrets.txt", ""):
            with self.subTest(value=hostile):
                self.assertIsNone(resolve(hostile))

    def test_uploads_reject_unsupported_formats(self) -> None:
        entry, why = save_upload("payload.svg", b"<svg/>")
        self.assertIsNone(entry)
        self.assertIn("unsupported", why.lower())

    def test_registry_is_a_tuple_and_never_raises(self) -> None:
        self.assertIsInstance(registry(), tuple)


if __name__ == "__main__":
    unittest.main()
