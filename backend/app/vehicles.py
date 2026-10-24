"""Vehicle fleet: real inventory rows the agent grounds availability on.

Rows are managed from the console (Fleet tab) or imported from an uploaded
CSV/XLSX catalogue. The agent queries this table for every availability and
price question — when nothing matches, the agent says the team will confirm
rather than inventing vehicles, rates or availability.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.database import Booking, Vehicle


class _Unset:
    """Sentinel for "field not supplied" so a partial update never clears data."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return False

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "UNSET"


UNSET = _Unset()

PACKAGE_HOURS = (6, 12, 24)


def package_price(vehicle: Vehicle, hours: int) -> float | None:
    """Rate-card price for a fixed 6/12/24 hour package (None when not offered)."""
    field = {6: "price_6h", 12: "price_12h", 24: "price_24h"}.get(int(hours or 0))
    if field is None:
        return None
    value = getattr(vehicle, field, None)
    return float(value) if value else None


def offers_packages(vehicle: Vehicle) -> list[int]:
    """Package durations this vehicle actually publishes a price for."""
    return [h for h in PACKAGE_HOURS if package_price(vehicle, h)]


def upsert_vehicle(
    db: DBSession, *, code: str, name: str, category: Any = UNSET,
    transmission: Any = UNSET, fuel: Any = UNSET, seats: Any = UNSET,
    price_per_day: Any = UNSET, price_per_hour: Any = UNSET,
    price_6h: Any = UNSET, price_12h: Any = UNSET, price_24h: Any = UNSET,
    deposit: Any = UNSET, driver_fee_per_day: Any = UNSET,
    mileage_limit_per_day: Any = UNSET, extra_km_charge: Any = UNSET,
    available: Any = UNSET, image_url: Any = UNSET, description: Any = UNSET,
    location: Any = UNSET,
) -> Vehicle:
    """Create or update a fleet row. Only fields actually supplied are written."""
    code = (code or "").strip().upper()
    if not code or not (name or "").strip():
        raise ValueError("code and name are required")
    row = db.execute(select(Vehicle).where(Vehicle.code == code)).scalars().first()
    if row is None:
        row = Vehicle(code=code, name=name.strip())
        db.add(row)

    supplied = {
        "category": category, "transmission": transmission, "fuel": fuel,
        "seats": seats, "price_per_day": price_per_day, "price_per_hour": price_per_hour,
        "price_6h": price_6h, "price_12h": price_12h, "price_24h": price_24h,
        "deposit": deposit, "driver_fee_per_day": driver_fee_per_day,
        "mileage_limit_per_day": mileage_limit_per_day, "extra_km_charge": extra_km_charge,
        "available": available, "image_url": image_url, "description": description,
        "location": location,
    }
    text_fields = {"category", "transmission", "fuel", "image_url", "description", "location"}
    for field, value in supplied.items():
        if isinstance(value, _Unset):
            continue
        if field in text_fields and isinstance(value, str):
            value = value.strip()
        setattr(row, field, value)
    if not isinstance(name, _Unset):
        row.name = (name or "").strip()
    db.flush()
    return row


def delete_vehicle(db: DBSession, code: str) -> bool:
    row = db.execute(select(Vehicle).where(Vehicle.code == code.strip().upper())).scalars().first()
    if row is None:
        return False
    active = db.execute(
        select(Booking.id).where(
            Booking.vehicle_id == row.id, Booking.status == "confirmed"
        ).limit(1)
    ).scalar_one_or_none()
    if active is not None:
        raise ValueError("vehicle has a confirmed booking — cancel it first")
    db.delete(row)
    return True


def _row_to_dict(v: Vehicle) -> dict[str, Any]:
    return {
        "code": v.code, "name": v.name, "category": v.category,
        "transmission": v.transmission, "fuel": v.fuel, "seats": v.seats,
        "price_per_day": v.price_per_day, "price_per_hour": v.price_per_hour,
        "price_6h": v.price_6h, "price_12h": v.price_12h, "price_24h": v.price_24h,
        "deposit": v.deposit, "driver_fee_per_day": v.driver_fee_per_day,
        "mileage_limit_per_day": v.mileage_limit_per_day,
        "extra_km_charge": v.extra_km_charge, "available": v.available,
        "image_url": v.image_url, "description": v.description, "location": v.location,
    }


def list_vehicles(db: DBSession, limit: int = 200) -> list[dict[str, Any]]:
    rows = db.execute(select(Vehicle).order_by(Vehicle.name).limit(limit)).scalars().all()
    return [_row_to_dict(v) for v in rows]


def search_vehicles(db: DBSession, query: str = "", limit: int = 8) -> list[Vehicle]:
    """Keyword-ranked fleet search used for prompt grounding.

    Only listed vehicles (available=1) are returned — a withdrawn car must
    never be offered to a customer.
    """
    terms = [t for t in re.findall(r"\w+", (query or "").lower()) if len(t) > 1]
    rows = db.execute(select(Vehicle).where(Vehicle.available == 1)).scalars().all()
    if not rows:
        return []
    if not terms:
        return rows[:limit]

    def score(v: Vehicle) -> float:
        hay = (f"{v.code} {v.name} {v.category} {v.transmission} {v.fuel} "
               f"{v.description}").lower()
        s = 0.0
        for t in terms:
            if t in hay:
                s += 1.0
            elif any(t in w for w in hay.split()):
                s += 0.5
        return s

    ranked = [v for v in rows if score(v) > 0]
    ranked.sort(key=score, reverse=True)
    return ranked[:limit] or rows[:limit]


def find_vehicle(
    db: DBSession, ref: str, *, include_unavailable: bool = False,
) -> Vehicle | None:
    """Look a vehicle up by code or by exact (case-insensitive) name.

    By default only LISTED (available=1) vehicles are returned: a withdrawn or
    parked car must never be quoted to a customer. Because is_free() only knows
    about bookings, this filter is the ONLY thing standing between a parked
    vehicle and a customer-facing price — callers that genuinely need to see a
    parked row (admin/diagnostics) must opt in explicitly.
    """
    ref = (ref or "").strip()
    if not ref:
        return None

    def _listed(query):
        if not include_unavailable:
            query = query.where(Vehicle.available == 1)
        return query

    row = db.execute(
        _listed(select(Vehicle).where(Vehicle.code == ref.upper()))
    ).scalars().first()
    if row is not None:
        return row
    return db.execute(
        _listed(select(Vehicle).where(Vehicle.name.ilike(ref)))
    ).scalars().first()


def image_for_query(db: DBSession, query: str = "", limit: int = 8) -> str:
    """Best-matching vehicle image URL for a customer query ("" when none).

    Reuses the same keyword ranking as the prompt grounding AND the one fleet
    image resolver, so the picture always belongs to a vehicle the agent
    actually quoted. A row whose photo is a LOCAL registry file is resolved to
    its public URL too — the returned value is always a link the console can
    render. Callers that must send a local file should use the registry id
    instead (see ``app.media.resolve_vehicle_image``).
    """
    from app.media import public_url, resolve, resolve_vehicle_image

    for v in search_vehicles(db, query, limit=limit):
        url, image_id = resolve_vehicle_image(
            v.image_url or "",
            code=v.code or "",
            name=v.name or "",
            category=v.category or "",
            description=v.description or "",
        )
        if url:
            return url[:500]
        if image_id:
            entry = resolve(image_id)
            if entry is not None:
                return public_url(entry)[:500]
    return ""


def categories(db: DBSession) -> list[str]:
    """Distinct categories of LISTED vehicles (for the tappable menu)."""
    rows = db.execute(select(Vehicle.category).where(Vehicle.available == 1)).all()
    seen: list[str] = []
    for (cat,) in rows:
        cat = (cat or "").strip()
        if cat and cat.lower() not in {c.lower() for c in seen}:
            seen.append(cat)
    return seen


def is_free(
    db: DBSession, vehicle_id: str, start: datetime, end: datetime,
    exclude_booking_id: str = "",
) -> bool:
    """True when no CONFIRMED booking overlaps [start, end) for this vehicle.

    Draft reservations never block a vehicle (they are only a conversation
    state); the actual block is checked again inside the confirm transaction.
    """
    q = select(Booking.id).where(
        Booking.vehicle_id == vehicle_id,
        Booking.status == "confirmed",
        Booking.start_at < end,
        Booking.end_at > start,
    )
    if exclude_booking_id:
        q = q.where(Booking.id != exclude_booking_id)
    return db.execute(q.limit(1)).scalar_one_or_none() is None


def alternatives(
    db: DBSession, start: datetime, end: datetime, category: str = "",
    exclude_vehicle_id: str = "", limit: int = 3,
) -> list[Vehicle]:
    """Honest alternatives: other LISTED vehicles free for the same window.

    Prefers the same category, then anything else that is genuinely free.
    """
    rows = db.execute(select(Vehicle).where(Vehicle.available == 1)).scalars().all()
    free = [
        v for v in rows
        if v.id != exclude_vehicle_id and is_free(db, v.id, start, end)
    ]
    same = [v for v in free if category and (v.category or "").lower() == category.lower()]
    rest = [v for v in free if v not in same]
    same.sort(key=lambda v: (v.price_24h or v.price_per_day or 0))
    rest.sort(key=lambda v: (v.price_24h or v.price_per_day or 0))
    return (same + rest)[:limit]


def parse_when(value: Any) -> datetime | None:
    """Parse an LLM-provided datetime string (ISO 8601) into an aware datetime.

    Naive values are treated as UTC; anything unparseable returns None so the
    caller asks the customer instead of guessing.
    """
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
