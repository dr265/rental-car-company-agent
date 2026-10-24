"""Starter fleet for ZoomRideXX Car Rentals.

The 17 cars below are the published rate card. Seeding is idempotent and
versioned: it runs once per database (setting ``seed:zoomride:fleet:v1``),
removes the old placeholder cars when they are not referenced by a booking,
and then upserts the rate-card fleet. Owner edits made after the seed are
never overwritten on later starts.

Every price here is real persisted data the agent quotes; nothing is invented
at reply time.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from app.database import Booking, FAQ, Setting, Vehicle
from app.vehicles import upsert_vehicle

log = logging.getLogger("zoomride.seed")

SEED_MARKER = "seed:zoomride:fleet:v1"

CATEGORY_NAMES = ["SUV & 4x4", "Compact SUV", "Sedan", "Hatchback & MUV"]

# code, name, category, rates (6h, 12h, 24h), deposit, fuel, seats,
# transmission, image id, description
FLEET: list[dict] = [
    {
        "code": "ZR-THAR-ROXX", "name": "Mahindra Thar Roxx", "category": "SUV & 4x4",
        "price_12h": 3500, "price_24h": 5000, "deposit": 5000,
        "fuel": "diesel", "seats": 5, "transmission": "automatic",
        "image_url": "thar-roxx",
        "description": "5-door Thar Roxx with a commanding view, comfortable for city runs and weekend escapes.",
    },
    {
        "code": "ZR-THAR-4X4", "name": "Mahindra Thar 4x4", "category": "SUV & 4x4",
        "price_12h": 2800, "price_24h": 4000, "deposit": 5000,
        "fuel": "diesel", "seats": 4, "transmission": "manual",
        "image_url": "thar-4x4",
        "description": "The original go-anywhere Thar 4x4 — a favourite for hill trips and rough roads.",
    },
    {
        "code": "ZR-SCORPIO-N", "name": "Mahindra Scorpio N", "category": "SUV & 4x4",
        "price_12h": 2800, "price_24h": 4000, "deposit": 5000,
        "fuel": "diesel", "seats": 7, "transmission": "automatic",
        "image_url": "scorpio-n",
        "description": "Seven-seat Scorpio N with a strong road presence and a comfortable highway ride.",
    },
    {
        "code": "ZR-SCORPIO-S11", "name": "Mahindra Scorpio S11", "category": "SUV & 4x4",
        "price_12h": 2800, "price_24h": 4000, "deposit": 5000,
        "fuel": "diesel", "seats": 7, "transmission": "manual",
        "image_url": "scorpio-s11",
        "description": "Rugged Scorpio S11, a dependable choice for family trips and outstation drives.",
    },
    {
        "code": "ZR-XUV-700", "name": "Mahindra XUV700", "category": "SUV & 4x4",
        "price_12h": 3500, "price_24h": 5000, "deposit": 5000,
        "fuel": "diesel", "seats": 7, "transmission": "automatic",
        "image_url": "xuv-700",
        "description": "Spacious XUV700 with premium interiors — great for long family journeys.",
    },
    {
        "code": "ZR-ENDEAVOUR", "name": "Ford Endeavour", "category": "SUV & 4x4",
        "price_12h": 6000, "price_24h": 10000, "deposit": 10000,
        "fuel": "diesel", "seats": 7, "transmission": "automatic",
        "image_url": "endeavour",
        "description": "Full-size Endeavour with generous space and a planted highway ride.",
    },
    {
        "code": "ZR-FORTUNER", "name": "Toyota Fortuner", "category": "SUV & 4x4",
        "price_12h": 10000, "price_24h": 14000, "deposit": 10000,
        "fuel": "diesel", "seats": 7, "transmission": "automatic",
        "image_url": "fortuner",
        "description": "The Fortuner — our flagship SUV for weddings, VIP movement and long trips. *Subject to availability at the hub.",
    },
    {
        "code": "ZR-ERTIGA", "name": "Maruti Suzuki Ertiga", "category": "Hatchback & MUV",
        "price_6h": 1000, "price_12h": 2200, "price_24h": 3000, "deposit": 3000,
        "fuel": "petrol", "seats": 7, "transmission": "manual",
        "image_url": "ertiga",
        "description": "Seven-seat Ertiga — the practical pick for family functions and airport runs.",
    },
    {
        "code": "ZR-FRONX", "name": "Maruti Suzuki Fronx", "category": "Compact SUV",
        "price_6h": 1000, "price_12h": 1200, "price_24h": 2100, "deposit": 5000,
        "fuel": "petrol", "seats": 5, "transmission": "manual",
        "image_url": "fronx",
        "description": "Stylish compact crossover with easy city manners and good mileage.",
    },
    {
        "code": "ZR-DZIRE", "name": "Maruti Suzuki Dzire", "category": "Sedan",
        "price_6h": 1000, "price_12h": 1200, "price_24h": 2100, "deposit": 3000,
        "fuel": "petrol", "seats": 5, "transmission": "manual",
        "image_url": "dzire",
        "description": "Comfortable sedan for meetings, airport transfers and everyday city use.",
    },
    {
        "code": "ZR-BALENO", "name": "Maruti Suzuki Baleno", "category": "Hatchback & MUV",
        "price_6h": 1000, "price_12h": 1500, "price_24h": 2400, "deposit": 3000,
        "fuel": "petrol", "seats": 5, "transmission": "automatic",
        "image_url": "baleno",
        "description": "Premium hatchback with a smooth automatic — light on fuel and easy to park.",
    },
    {
        "code": "ZR-SWIFT", "name": "Maruti Suzuki Swift", "category": "Hatchback & MUV",
        "price_6h": 1000, "price_12h": 1500, "price_24h": 2400, "deposit": 3000,
        "fuel": "petrol", "seats": 5, "transmission": "manual",
        "image_url": "swift",
        "description": "Quick, fuel-efficient Swift for solo trips and daily city driving.",
    },
    {
        "code": "ZR-AURA", "name": "Hyundai Aura", "category": "Sedan",
        "price_6h": 1000, "price_12h": 1500, "price_24h": 2400, "deposit": 3000,
        "fuel": "petrol", "seats": 5, "transmission": "manual",
        "image_url": "aura",
        "description": "Compact sedan with a roomy boot and a comfortable back seat.",
    },
    {
        "code": "ZR-BREZZA", "name": "Maruti Suzuki Brezza", "category": "Compact SUV",
        "price_6h": 1200, "price_12h": 1800, "price_24h": 2700, "deposit": 5000,
        "fuel": "petrol", "seats": 5, "transmission": "automatic",
        "image_url": "brezza",
        "description": "Compact SUV with a high seating position and an easy automatic.",
    },
    {
        "code": "ZR-CRETA", "name": "Hyundai Creta", "category": "Compact SUV",
        "price_6h": 1200, "price_12h": 1800, "price_24h": 2700, "deposit": 5000,
        "fuel": "diesel", "seats": 5, "transmission": "automatic",
        "image_url": "creta",
        "description": "Creta automatic — refined, spacious and our most requested city SUV.",
    },
    {
        "code": "ZR-VERNA", "name": "Hyundai Verna", "category": "Sedan",
        "price_6h": 1500, "price_12h": 2200, "price_24h": 3000, "deposit": 3000,
        "fuel": "petrol", "seats": 5, "transmission": "automatic",
        "image_url": "verna",
        "description": "Premium sedan with a quiet cabin, ideal for business travel.",
    },
    {
        "code": "ZR-VENUE", "name": "Hyundai Venue", "category": "Compact SUV",
        "price_6h": 1500, "price_12h": 2200, "price_24h": 3000, "deposit": 5000,
        "fuel": "petrol", "seats": 5, "transmission": "automatic",
        "image_url": "venue",
        "description": "Compact SUV that is nimble in traffic and comfortable on the highway.",
    },
]

RENTAL_FAQS: list[tuple[str, str, str]] = [
    (
        "What documents do I need to rent a car?",
        "For self-drive, please share a clear photo of your driving licence (front and back) "
        "and one government ID (Aadhaar or Voter ID) on WhatsApp before pickup. You can also "
        "show the originals at handover.",
        "KYC",
    ),
    (
        "How much is the security deposit?",
        "The refundable deposit is shown with every car: ₹3,000 for hatchbacks and sedans, "
        "₹5,000 for compact SUVs and most SUVs, and ₹10,000 for the Fortuner and Endeavour. "
        "It is returned after the car is checked back in.",
        "Deposit",
    ),
    (
        "Is fuel included in the rental?",
        "No. The car is handed over with a set fuel level and should be returned at the same "
        "level. Fuel used during the rental is payable by the customer.",
        "Rental",
    ),
    (
        "What is the mileage limit?",
        "Self-drive rentals include 250 km per 24 hours. Extra kilometres are charged at "
        "₹12 per km. Chauffeur-driven trips are quoted separately for outstation travel.",
        "Rental",
    ),
    (
        "Do you deliver the car to my address?",
        "Yes, doorstep delivery and pickup are available within the city for ₹500. Share your "
        "address and preferred time, and our fleet desk will confirm the slot.",
        "Delivery",
    ),
    (
        "Can I cancel a booking?",
        "You can cancel free of charge before the rental starts. Once the car has been handed "
        "over, please speak to our fleet desk.",
        "Bookings",
    ),
    (
        "Is a chauffeur available?",
        "Yes. Choose With Chauffeur while booking. The chauffeur charge is added to the "
        "package price and shown before you confirm.",
        "Chauffeur",
    ),
]


def _seed_faqs(db: DBSession) -> None:
    known = {q for (q,) in db.execute(select(FAQ.question)).all()}
    for index, (question, answer, category) in enumerate(RENTAL_FAQS):
        if question in known:
            continue
        db.add(FAQ(
            question=question, answer=answer, category=category,
            sort_order=index, active=1,
        ))


def _remove_placeholder_fleet(db: DBSession) -> None:
    placeholders = {
        "CAR-SELTOS-01", "CAR-MARUTI-01", "CAR-HONDA-01", "CAR-MARUTI-02",
    }
    for row in db.execute(select(Vehicle)).scalars().all():
        if row.code not in placeholders:
            continue
        used = db.scalar(
            select(func.count(Booking.id)).where(Booking.vehicle_id == row.id)
        ) or 0
        if used == 0:
            db.delete(row)
    db.flush()


def ensure_seed(db: DBSession) -> None:
    """Seed the rate-card fleet exactly once per database."""
    marker = db.get(Setting, SEED_MARKER)
    if marker is None:
        _remove_placeholder_fleet(db)
        for index, row in enumerate(FLEET):
            upsert_vehicle(
                db,
                code=row["code"],
                name=row["name"],
                category=row["category"],
                transmission=row.get("transmission", ""),
                fuel=row.get("fuel", ""),
                seats=row.get("seats"),
                price_6h=row.get("price_6h"),
                price_12h=row.get("price_12h"),
                price_24h=row.get("price_24h"),
                price_per_day=row.get("price_24h"),
                deposit=row.get("deposit"),
                driver_fee_per_day=800,
                mileage_limit_per_day=250,
                extra_km_charge=12,
                available=1,
                image_url=row.get("image_url", ""),
                description=row.get("description", ""),
                location="ZoomRideXX Hub",
            )
            db.flush()
        db.add(Setting(key=SEED_MARKER, value="1"))
        log.info("seeded ZoomRideXX rate-card fleet (%s cars)", len(FLEET))

    existing_faqs = db.scalar(select(func.count(FAQ.id))) or 0
    if existing_faqs == 0:
        _seed_faqs(db)
        log.info("seeded %s rental FAQs", len(RENTAL_FAQS))

    db.commit()
