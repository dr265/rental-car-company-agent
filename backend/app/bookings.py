"""Booking service: quotes, confirmed reservations, cancellation policy.

Design rules (all enforced here, never in the prompt):
  • A quote is always labelled an ESTIMATE — the final charge is settled at
    pickup; the agent must not promise otherwise.
  • A booking row only leaves status 'draft' after an explicit customer
    confirmation event (the WhatsApp Confirm tap), never from LLM text alone.
  • Confirmation is idempotent: the confirming WhatsApp message id is stored on
    the booking; replaying the same tap returns the SAME booking.
  • Overlap protection: two confirmed bookings for one vehicle can never
    intersect ([start, end) windows), re-checked inside the confirm step.
  • References look like RC-A1B2C3 and are unique (checked before commit).
"""
from __future__ import annotations

import logging
import math
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.config import (
    RENTAL_CURRENCY,
    RENTAL_DELIVERY_FEE,
    RENTAL_DRIVER_FEE_PER_DAY,
    RENTAL_MAX_BOOKING_DAYS,
    RENTAL_MIN_LEAD_HOURS,
)
from app.database import Booking, Customer, Vehicle
from app.vehicles import is_free

log = logging.getLogger("rental.bookings")

_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusion


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def rental_days(start: datetime, end: datetime) -> int:
    """Whole rental days: any started day counts (24h blocks, min 1)."""
    seconds = max(0.0, (end - start).total_seconds())
    return max(1, math.ceil(seconds / 86400 - 1e-9))


def validate_window(start: datetime | None, end: datetime | None) -> str:
    """'' when the requested window is bookable, else a human-readable reason."""
    if start is None or end is None:
        return "pickup and return times are required"
    if end <= start:
        return "the return time must be after the pickup time"
    if start < _now() - timedelta(minutes=5):
        return "the pickup time is in the past"
    if start < _now() + timedelta(hours=RENTAL_MIN_LEAD_HOURS):
        return f"we need at least {RENTAL_MIN_LEAD_HOURS} hour(s) of preparation time"
    if rental_days(start, end) > RENTAL_MAX_BOOKING_DAYS:
        return f"rentals are limited to {RENTAL_MAX_BOOKING_DAYS} days per booking"
    return ""


def quote(
    vehicle: Vehicle, start: datetime, end: datetime,
    with_driver: bool = False, delivery: bool = False,
    hours: int | None = None,
) -> dict:
    """Deterministic cost breakdown for one vehicle + package.

    When ``hours`` matches a published 6/12/24-hour package, that rate-card
    price is the base. Otherwise the quote falls back to whole rental days.
    The total is an ESTIMATE; the deposit is always listed separately.
    """
    from app.vehicles import package_price

    package = package_price(vehicle, hours) if hours else None
    per_day = float(vehicle.price_per_day or 0)
    if package is not None:
        days = 1
        base = package
        package_hours = int(hours)
    else:
        if not per_day:
            # Rate-card rows publish 6/12/24-hour packages instead of a per-day
            # price; a multi-day quote derives the daily rate from the 24h
            # package so a long rental can never silently quote ₹0.
            per_day = float(vehicle.price_24h or 0)
        days = rental_days(start, end)
        base = days * per_day
        package_hours = None
    if with_driver:
        driver_rate = float(
            vehicle.driver_fee_per_day
            if vehicle.driver_fee_per_day is not None
            else RENTAL_DRIVER_FEE_PER_DAY
        )
        if package_hours:
            # A 6/12-hour package is a fraction of the day rate.
            driver_fee = float(round(driver_rate * package_hours / 24 / 50) * 50)
        else:
            driver_fee = days * driver_rate
    else:
        driver_fee = 0.0
    delivery_fee = float(RENTAL_DELIVERY_FEE) if delivery else 0.0
    total = base + driver_fee + delivery_fee
    return {
        "days": days,
        "duration_hours": package_hours,
        "price_per_day": per_day,
        "package_price": package,
        "base_amount": base,
        "driver_fee": driver_fee,
        "delivery_fee": delivery_fee,
        "total_estimate": total,
        "deposit": float(vehicle.deposit or 0),
        "currency": RENTAL_CURRENCY,
        "mileage_limit_per_day": vehicle.mileage_limit_per_day,
        "extra_km_charge": vehicle.extra_km_charge,
        "with_driver": bool(with_driver),
    }


def breakdown_text(v: Vehicle, q: dict, start: datetime, end: datetime) -> str:
    """Plain-text cost breakdown the agent can paste into a reply."""
    cur = q["currency"]
    if q.get("duration_hours"):
        lines = [f"{v.name} ({v.code})", f"• {q['duration_hours']}-hour package: {cur}{q['base_amount']:,.0f}"]
    else:
        lines = [
            f"{v.name} ({v.code})",
            f"• {q['days']} day(s) × {cur}{q['price_per_day']:,.0f} = {cur}{q['base_amount']:,.0f}",
        ]
    if q["driver_fee"]:
        lines.append(f"• Chauffeur: {cur}{q['driver_fee']:,.0f}")
    if q["delivery_fee"]:
        lines.append(f"• Delivery/collection: {cur}{q['delivery_fee']:,.0f}")
    lines.append(f"• *Estimated total: {cur}{q['total_estimate']:,.0f}*")
    if q["deposit"]:
        lines.append(f"• Refundable deposit: {cur}{q['deposit']:,.0f} (separate)")
    if q["mileage_limit_per_day"]:
        extra = f" + {cur}{q['extra_km_charge']:,.0f}/km extra" if q["extra_km_charge"] else ""
        lines.append(f"• Includes {q['mileage_limit_per_day']:,.0f} km/day{extra}")
    return "\n".join(lines)


def new_reference(db: DBSession) -> str:
    """Unique booking reference RC-XXXXXX (checked against the database)."""
    for _ in range(20):
        ref = "RC-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(6))
        exists = db.execute(select(Booking.id).where(Booking.reference == ref)).first()
        if exists is None:
            return ref
    raise RuntimeError("could not allocate a unique booking reference")


def draft_for(db: DBSession, conversation_id: str) -> Booking | None:
    """The open draft booking for a conversation (there is at most one).

    The conversation link lives in `notes` as "conv=<id>", so an EMPTY id must
    short-circuit: the LIKE pattern would otherwise degrade to "%conv=%" and
    match whatever other conversation's draft was touched most recently — a
    cross-customer leak. Never look a draft up without a real conversation id.
    """
    if not (conversation_id or "").strip():
        return None
    return db.execute(
        select(Booking)
        .where(Booking.notes.like(f"%conv={conversation_id}%"), Booking.status == "draft")
        .order_by(Booking.created_at.desc())
    ).scalars().first()


def create_draft(
    db: DBSession, *, customer: Customer, vehicle: Vehicle, start: datetime,
    end: datetime, pickup_location: str = "", dropoff_location: str = "",
    with_driver: bool = False, delivery: bool = False, conversation_id: str = "",
    hours: int | None = None, drive_mode: str = "", handover: str = "",
    kyc_mode: str = "",
) -> Booking:
    """Create or refresh the open draft for this conversation."""
    draft = draft_for(db, conversation_id) if conversation_id else None
    if draft is None:
        draft = Booking(customer_id=customer.id, vehicle_id=vehicle.id)
        db.add(draft)
    q = quote(vehicle, start, end, with_driver=with_driver, delivery=delivery,
              hours=hours)
    draft.vehicle_id = vehicle.id
    draft.start_at = start
    draft.end_at = end
    draft.pickup_location = pickup_location[:200]
    draft.dropoff_location = dropoff_location[:200]
    draft.with_driver = 1 if with_driver else 0
    draft.duration_hours = q["duration_hours"]
    draft.drive_mode = (drive_mode or ("chauffeur" if with_driver else "self"))[:16]
    draft.handover = (handover or ("doorstep" if delivery else "hub"))[:16]
    draft.kyc_mode = (kyc_mode or "")[:24]
    draft.days = q["days"]
    draft.price_per_day = q["price_per_day"]
    draft.driver_fee = q["driver_fee"]
    draft.delivery_fee = q["delivery_fee"]
    draft.base_amount = q["base_amount"]
    draft.total_estimate = q["total_estimate"]
    draft.deposit = q["deposit"]
    draft.currency = q["currency"]
    if conversation_id:
        # keep the conversation link in notes (no extra column needed)
        notes = draft.notes or ""
        if f"conv={conversation_id}" not in notes:
            draft.notes = (notes + f" conv={conversation_id}").strip()[:500]
    db.flush()
    return draft


def confirm_draft(
    db: DBSession, *, draft: Booking, confirming_message_id: str = "",
) -> tuple[Booking | None, str]:
    """Confirm a draft after the customer tapped Confirm.

    Returns (booking, "") on success or (None, reason) when it cannot proceed
    (vehicle withdrawn, window invalid, or the vehicle got booked meanwhile).
    Replay-safe: the same confirming message id returns the same booking.
    """
    if draft.status != "draft":
        if draft.status == "confirmed":
            return draft, ""  # replay of the same confirmation
        return None, "this reservation is no longer active"
    vehicle = db.get(Vehicle, draft.vehicle_id)
    if vehicle is None or not vehicle.available:
        return None, "that vehicle is no longer available"
    if confirming_message_id:
        existing = db.execute(
            select(Booking).where(
                Booking.status == "confirmed",
                Booking.source_message_id == confirming_message_id,
            )
        ).scalars().first()
        if existing is not None:
            return existing, ""  # exact duplicate tap
    start = _aware(draft.start_at)
    end = _aware(draft.end_at)
    problem = validate_window(start, end)
    if problem:
        return None, problem
    if not is_free(db, vehicle.id, start, end, exclude_booking_id=draft.id):
        return None, "the vehicle was just booked for that window"
    # Recompute the quote from the CURRENT vehicle data (prices may have changed
    # while the draft sat open) — never trust the stale draft numbers for money.
    q = quote(vehicle, start, end, with_driver=bool(draft.with_driver),
              delivery=bool(draft.delivery_fee),
              hours=draft.duration_hours)
    draft.days = q["days"]
    draft.duration_hours = q["duration_hours"]
    draft.price_per_day = q["price_per_day"]
    draft.driver_fee = q["driver_fee"]
    draft.delivery_fee = q["delivery_fee"]
    draft.base_amount = q["base_amount"]
    draft.total_estimate = q["total_estimate"]
    draft.deposit = q["deposit"]
    draft.reference = new_reference(db)
    draft.status = "confirmed"
    draft.confirmed_at = _now()
    draft.source_message_id = (confirming_message_id or "")[:80]
    db.commit()
    log.info("booking %s confirmed for %s (%s → %s)",
             draft.reference, vehicle.code, start, end)
    return draft, ""


def cancel(db: DBSession, booking: Booking, by_customer: bool = True) -> tuple[bool, str]:
    """Cancel per the business policy: free before pickup, staff-only after."""
    if booking.status == "cancelled":
        return True, ""
    if booking.status != "confirmed":
        return False, "only confirmed reservations can be cancelled"
    start = _aware(booking.start_at)
    if by_customer and start is not None and _now() >= start:
        return False, "the rental has started — please contact our staff"
    booking.status = "cancelled"
    booking.cancelled_at = _now()
    db.commit()
    log.info("booking %s cancelled", booking.reference)
    return True, ""


def customer_bookings(db: DBSession, customer_id: str, limit: int = 10) -> list[Booking]:
    """Bookings owned by ONE customer — the only rows a customer may see."""
    return db.execute(
        select(Booking)
        .where(Booking.customer_id == customer_id, Booking.status.in_(("confirmed", "draft")))
        .order_by(Booking.start_at.desc())
        .limit(limit)
    ).scalars().all()


def find_by_reference(db: DBSession, customer_id: str, reference: str) -> Booking | None:
    """Reference lookup SCOPED to the requesting customer (ownership check)."""
    ref = (reference or "").strip().upper()
    if not ref:
        return None
    return db.execute(
        select(Booking).where(
            Booking.reference == ref, Booking.customer_id == customer_id
        )
    ).scalars().first()


def booking_summary(b: Booking, vehicle: Vehicle | None) -> str:
    """Compact one-line summary used in replies and console lists."""
    cur = b.currency or RENTAL_CURRENCY
    start = _aware(b.start_at)
    end = _aware(b.end_at)

    def fmt(dt: datetime | None) -> str:
        return dt.strftime("%d %b %Y, %I:%M %p") if dt else "?"

    name = vehicle.name if vehicle else "vehicle"
    duration = (f"{b.duration_hours}h package" if b.duration_hours
                else f"{b.days} day(s)")
    return (
        f"{b.reference or '(draft)'} · {name} · {fmt(start)} → {fmt(end)} · "
        f"{duration} · est. {cur}{b.total_estimate:,.0f}"
        f"{' · with chauffeur' if b.with_driver else ' · self-drive'}"
    )
