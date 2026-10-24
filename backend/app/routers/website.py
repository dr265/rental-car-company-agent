"""Public website API for the ZoomRideXX customer site.

Everything the customer-facing React site needs, backed by the SAME database,
booking service and fleet table the WhatsApp agent uses — one source of truth,
no duplicated pricing logic:

  GET  /api/site/config              public business profile + WhatsApp number
  GET  /api/site/vehicles            listed fleet with resolved photo URLs
  GET  /api/site/vehicles/{code}     one vehicle (+ optional window availability)
  POST /api/site/quote               deterministic price breakdown for a window
  POST /api/site/bookings            direct website booking (validated, persisted)
  GET  /api/site/bookings/{ref}      booking status, scoped to the customer phone
  POST /api/site/concierge           the WhatsApp agent brain, without the send

Server-side rules (never trusted from the browser):
  • window validation + lead time + max duration  (app.bookings.validate_window)
  • overlap protection against CONFIRMED bookings (app.vehicles.is_free)
  • money ALWAYS recomputed here from the fleet row  (app.bookings.quote)
  • a confirmed booking gets a real RC-XXXXXX reference and a real customer row
  • the owner desk receives the same WhatsApp alert as WhatsApp bookings
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.bookings import new_reference, quote, validate_window
from app.config import (
    MEDIA_URL_PATH,
    PUBLIC_BASE_URL,
    RENTAL_DELIVERY_FEE,
    RENTAL_DEPOSIT_REQUIRED,
    RENTAL_DRIVER_FEE_PER_DAY,
    RENTAL_LICENSE_REQUIRED,
    RENTAL_MAX_BOOKING_DAYS,
    RENTAL_MIN_LEAD_HOURS,
    RENTAL_CURRENCY,
    WA_BUSINESS_NUMBER,
    llm_configured,
)
from app.database import Booking, Customer, SessionLocal, Vehicle, get_db
from app.kapso import kapso, normalize_phone
from app.menu import DESK_PHONES, HUB_ADDRESS, TAGLINE
from app.persona import get_persona
from app.vehicles import (
    find_vehicle,
    is_free,
    alternatives,
    package_price,
    parse_when,
)

log = logging.getLogger("rental.api.site")

router = APIRouter(prefix="/api/site", tags=["Website"])

_PACKAGE_HOURS = (6, 12, 24)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _relative_media_url(url: str) -> str:
    """Same-origin path for a media URL when the base is this backend.

    The site is served BY the backend, so a relative '/media/assets/…' path is
    correct for the browser, avoids localhost/127.0.0.1 host mismatches, and
    keeps working behind a reverse proxy. A genuinely external host (public
    media base) is returned unchanged.
    """
    url = (url or "").strip()
    if not url:
        return ""
    for base in (PUBLIC_BASE_URL, ):
        if base and url.lower().startswith(base.lower()):
            return url[len(base):] or "/"
    parsed = re.match(r"^https?://[^/]+(/.*)$", url, re.IGNORECASE)
    if parsed:
        path = parsed.group(1)
        if path.startswith(f"{MEDIA_URL_PATH}/"):
            return path
    return url


def _vehicle_image_url(db: DBSession, v: Vehicle) -> str:
    """Public (same-origin) photo URL for one fleet row — '' when none."""
    from app.media import public_url, resolve, resolve_vehicle_image

    try:
        url, image_id = resolve_vehicle_image(
            v.image_url or "", code=v.code or "", name=v.name or "",
            category=v.category or "", description=v.description or "",
        )
        if not url and image_id:
            entry = resolve(image_id)
            if entry is not None:
                url = public_url(entry)
        return _relative_media_url(url)
    except Exception:  # noqa: BLE001 — a broken image must never break the API
        return ""


def _packages(v: Vehicle) -> list[int]:
    return [h for h in _PACKAGE_HOURS if package_price(v, h)]


def _vehicle_dict(db: DBSession, v: Vehicle) -> dict[str, Any]:
    return {
        "code": v.code,
        "name": v.name,
        "category": v.category or "",
        "transmission": v.transmission or "",
        "fuel": v.fuel or "",
        "seats": v.seats,
        "price_6h": v.price_6h,
        "price_12h": v.price_12h,
        "price_24h": v.price_24h,
        "price_per_day": v.price_per_day,
        "packages": _packages(v),
        "deposit": float(v.deposit or 0),
        "driver_fee_per_day": v.driver_fee_per_day,
        "mileage_limit_per_day": v.mileage_limit_per_day,
        "extra_km_charge": v.extra_km_charge,
        "description": v.description or "",
        "location": v.location or "",
        "image_url": _vehicle_image_url(db, v),
    }


def _alternative_dicts(db: DBSession, start: datetime, end: datetime,
                       category: str = "", exclude_id: str = "") -> list[dict]:
    return [
        _vehicle_dict(db, v)
        for v in alternatives(db, start, end, category=category,
                              exclude_vehicle_id=exclude_id, limit=3)
    ]


def _booking_dict(db: DBSession, b: Booking) -> dict[str, Any]:
    v = db.get(Vehicle, b.vehicle_id)
    c = db.get(Customer, b.customer_id)
    return {
        "reference": b.reference or "",
        "status": b.status,
        "vehicle_code": v.code if v else "",
        "vehicle_name": v.name if v else "",
        "customer_name": (c.name or c.whatsapp_name or "") if c else "",
        "customer_phone": (c.display_phone or f"+{c.phone}") if c else "",
        "start_at": b.start_at.isoformat() if b.start_at else None,
        "end_at": b.end_at.isoformat() if b.end_at else None,
        "duration_hours": b.duration_hours,
        "days": b.days,
        "drive_mode": b.drive_mode or ("chauffeur" if b.with_driver else "self"),
        "handover": b.handover or "hub",
        "pickup_location": b.pickup_location or "",
        "dropoff_location": b.dropoff_location or "",
        "base_amount": float(b.base_amount or 0),
        "driver_fee": float(b.driver_fee or 0),
        "delivery_fee": float(b.delivery_fee or 0),
        "total_estimate": float(b.total_estimate or 0),
        "deposit": float(b.deposit or 0),
        "currency": b.currency or RENTAL_CURRENCY,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


def _window_from_payload(start_raw: Any, end_raw: Any) -> tuple[datetime, datetime]:
    start = parse_when(start_raw)
    end = parse_when(end_raw)
    if start is None or end is None:
        raise HTTPException(status_code=422, detail="pickup and return times are required")
    problem = validate_window(start, end)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    return start, end


def _hours_for_window(start: datetime, end: datetime) -> int | None:
    """The published package the window actually is (None → multi-day)."""
    span = (end - start).total_seconds() / 3600
    for hours in _PACKAGE_HOURS:
        if abs(span - hours) < 0.011:
            return hours
    return None


def _site_quote(v: Vehicle, start: datetime, end: datetime, *,
                with_driver: bool, delivery: bool) -> dict:
    """Deterministic breakdown for the website, mirroring app.bookings.quote.

    An exact 6/12/24-hour window uses that package price. Anything longer is
    whole days × the published full-day rate (the 24h package when the row has
    no separate per-day price) — the same rate card WhatsApp quotes from.
    """
    hours = _hours_for_window(start, end)
    if hours is not None and package_price(v, hours) is None:
        offered = _packages(v)
        raise HTTPException(
            status_code=422,
            detail=(f"the {hours}-hour package is not offered for {v.name} — "
                    f"available packages: {', '.join(str(h) + 'h' for h in offered)}"
                    if offered else
                    f"{v.name} has no published package prices — please contact the fleet desk"),
        )
    q = quote(v, start, end, with_driver=with_driver, delivery=delivery, hours=hours)
    if q["package_price"] is None and not q["base_amount"]:
        per_day = float(v.price_24h or v.price_per_day or 0)
        if not per_day:
            raise HTTPException(
                status_code=422,
                detail=f"{v.name} has no published daily rate — please contact the fleet desk",
            )
    return q


# --------------------------------------------------------------------------- #
# site config
# --------------------------------------------------------------------------- #
@router.get("/config")
async def site_config(db: DBSession = Depends(get_db)) -> dict:
    persona = get_persona(db)
    return {
        "business": {
            "name": persona.get("shop_name"),
            "assistant_name": persona.get("assistant_name"),
            "tagline": TAGLINE,
            "description": persona.get("business_description"),
            "working_hours": persona.get("working_hours"),
            "store_location": persona.get("store_location"),
            "contact_info": persona.get("contact_info"),
            "desk_phones": list(DESK_PHONES),
            "hub_address": HUB_ADDRESS,
        },
        "whatsapp_number": WA_BUSINESS_NUMBER,
        "currency": RENTAL_CURRENCY,
        "driver_fee_per_day": RENTAL_DRIVER_FEE_PER_DAY,
        "delivery_fee": RENTAL_DELIVERY_FEE,
        "min_lead_hours": RENTAL_MIN_LEAD_HOURS,
        "max_booking_days": RENTAL_MAX_BOOKING_DAYS,
        "deposit_required": RENTAL_DEPOSIT_REQUIRED,
        "license_required": RENTAL_LICENSE_REQUIRED,
        "llm_configured": llm_configured(),
    }


# --------------------------------------------------------------------------- #
# fleet
# --------------------------------------------------------------------------- #
@router.get("/vehicles")
async def site_vehicles(db: DBSession = Depends(get_db)) -> dict:
    rows = db.execute(
        select(Vehicle).where(Vehicle.available == 1).order_by(Vehicle.name)
    ).scalars().all()
    vehicles = [_vehicle_dict(db, v) for v in rows]
    categories: list[str] = []
    for v in vehicles:
        cat = v["category"]
        if cat and cat.lower() not in {c.lower() for c in categories}:
            categories.append(cat)
    return {"vehicles": vehicles, "categories": categories}


@router.get("/vehicles/{code}")
async def site_vehicle(
    code: str, start_at: str = "", end_at: str = "",
    db: DBSession = Depends(get_db),
) -> dict:
    v = find_vehicle(db, code)
    if v is None:
        raise HTTPException(status_code=404, detail="vehicle not found")
    payload: dict[str, Any] = {"vehicle": _vehicle_dict(db, v)}
    if start_at and end_at:
        start = parse_when(start_at)
        end = parse_when(end_at)
        if start is None or end is None:
            raise HTTPException(status_code=422, detail="invalid pickup or return time")
        payload["available"] = is_free(db, v.id, start, end)
        if not payload["available"]:
            payload["alternatives"] = _alternative_dicts(
                db, start, end, category=v.category or "", exclude_id=v.id)
    return payload


# --------------------------------------------------------------------------- #
# quote + availability
# --------------------------------------------------------------------------- #
class QuotePayload(BaseModel):
    vehicle_code: str = Field(min_length=1, max_length=64)
    start_at: str = Field(min_length=8, max_length=40)
    end_at: str = Field(min_length=8, max_length=40)
    with_driver: bool = False
    delivery: bool = False


@router.post("/quote")
async def site_quote(payload: QuotePayload, db: DBSession = Depends(get_db)) -> dict:
    v = find_vehicle(db, payload.vehicle_code)
    if v is None:
        raise HTTPException(status_code=404, detail="vehicle not found")
    start, end = _window_from_payload(payload.start_at, payload.end_at)
    if not is_free(db, v.id, start, end):
        return {
            "available": False,
            "quote": None,
            "alternatives": _alternative_dicts(
                db, start, end, category=v.category or "", exclude_id=v.id),
        }
    q = _site_quote(v, start, end, with_driver=payload.with_driver,
                    delivery=payload.delivery)
    return {"available": True, "quote": q, "alternatives": []}


# --------------------------------------------------------------------------- #
# direct website booking
# --------------------------------------------------------------------------- #
class BookingPayload(BaseModel):
    vehicle_code: str = Field(min_length=1, max_length=64)
    start_at: str = Field(min_length=8, max_length=40)
    end_at: str = Field(min_length=8, max_length=40)
    with_driver: bool = False
    delivery: bool = False
    pickup_location: str = Field(default="", max_length=200)
    dropoff_location: str = Field(default="", max_length=200)
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=10, max_length=20)
    notes: str = Field(default="", max_length=500)
    # client-generated key so a retried submit can never double-book
    idempotency_key: str = Field(default="", max_length=64)


async def _notify_website_booking(booking_id: str) -> None:
    """Owner-desk WhatsApp alert for a website booking (same copy as WhatsApp
    bookings; best-effort — a transport failure never rolls the booking back)."""
    from app.config import OWNER_WHATSAPP_NUMBERS
    from app.menu import owner_alert_text

    db = SessionLocal()
    try:
        b = db.get(Booking, booking_id)
        if b is None or b.status != "confirmed":
            return
        if not kapso.configured:
            log.warning("website booking %s: Kapso not configured — owner alert skipped",
                        b.reference)
            return
        v = db.get(Vehicle, b.vehicle_id)
        c = db.get(Customer, b.customer_id)
        text = owner_alert_text(b, v, c, address=b.pickup_location or "")
        for raw in OWNER_WHATSAPP_NUMBERS:
            try:
                await kapso.send_text(normalize_phone(raw), text)
            except Exception as exc:  # noqa: BLE001
                log.error("owner alert to …%s failed: %s", str(raw)[-4:], exc)
    finally:
        db.close()


@router.post("/bookings", status_code=201)
async def site_booking(
    payload: BookingPayload, background: BackgroundTasks,
    db: DBSession = Depends(get_db),
) -> dict:
    v = find_vehicle(db, payload.vehicle_code)
    if v is None:
        raise HTTPException(status_code=404, detail="vehicle not found")
    start, end = _window_from_payload(payload.start_at, payload.end_at)

    # idempotent submit: the same key always returns the SAME booking
    idem = (payload.idempotency_key or "").strip()
    if idem:
        existing = db.execute(
            select(Booking).where(
                Booking.source_message_id == f"web:{idem}",
                Booking.status == "confirmed",
            )
        ).scalars().first()
        if existing is not None:
            return {"booking": _booking_dict(db, existing), "duplicate": True}

    if not is_free(db, v.id, start, end):
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"{v.name} is already booked for that window",
                "alternatives": _alternative_dicts(
                    db, start, end, category=v.category or "", exclude_id=v.id),
            },
        )

    digits = normalize_phone(payload.phone)
    if len(digits) < 10:
        raise HTTPException(status_code=422, detail="a valid WhatsApp number is required")

    customer = db.execute(
        select(Customer).where(Customer.phone == digits)
    ).scalars().first()
    if customer is None:
        customer = Customer(
            phone=digits,
            display_phone=f"+{digits}",
            name=payload.name.strip()[:120],
            whatsapp_name=payload.name.strip()[:120],
        )
        db.add(customer)
        db.flush()
    elif payload.name.strip() and not customer.name:
        customer.name = payload.name.strip()[:120]

    q = _site_quote(v, start, end, with_driver=payload.with_driver,
                    delivery=payload.delivery)
    hours = q["duration_hours"]
    booking = Booking(
        customer_id=customer.id,
        vehicle_id=v.id,
        status="confirmed",
        start_at=start,
        end_at=end,
        pickup_location=payload.pickup_location.strip()[:200],
        dropoff_location=payload.dropoff_location.strip()[:200],
        with_driver=1 if payload.with_driver else 0,
        days=q["days"],
        duration_hours=hours,
        drive_mode="chauffeur" if payload.with_driver else "self",
        handover="doorstep" if payload.delivery else "hub",
        kyc_mode="handover",
        price_per_day=q["price_per_day"],
        driver_fee=q["driver_fee"],
        delivery_fee=q["delivery_fee"],
        base_amount=q["base_amount"],
        total_estimate=q["total_estimate"],
        deposit=q["deposit"],
        currency=q["currency"],
        notes=(f"source=website {payload.notes.strip()}"[:500]).strip(),
        source_message_id=f"web:{idem or uuid4().hex[:12]}",
        reference=new_reference(db),
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(booking)
    db.commit()
    log.info("website booking %s confirmed for %s (%s → %s)",
             booking.reference, v.code, start, end)

    background.add_task(_notify_website_booking, booking.id)
    return {"booking": _booking_dict(db, booking), "duplicate": False}


# --------------------------------------------------------------------------- #
# booking status (privacy-scoped)
# --------------------------------------------------------------------------- #
@router.get("/bookings/{reference}")
async def site_booking_status(
    reference: str, phone: str = "", db: DBSession = Depends(get_db),
) -> dict:
    """Lookup scoped to the requesting phone: a wrong number is a plain 404,
    so references alone never leak another customer's reservation."""
    ref = (reference or "").strip().upper()
    digits = normalize_phone(phone)
    if not ref or not digits:
        raise HTTPException(status_code=422, detail="reference and phone are required")
    row = db.execute(
        select(Booking).where(Booking.reference == ref)
    ).scalars().first()
    customer = db.get(Customer, row.customer_id) if row else None
    if row is None or customer is None or customer.phone != digits:
        raise HTTPException(status_code=404, detail="booking not found")
    return {"booking": _booking_dict(db, row)}


# --------------------------------------------------------------------------- #
# concierge — the WhatsApp agent brain for the website chat
# --------------------------------------------------------------------------- #
class ConciergePayload(BaseModel):
    session_id: str = Field(min_length=6, max_length=64)
    message: str = Field(min_length=1, max_length=1000)
    name: str = Field(default="", max_length=120)


_last_site_turn: dict[str, float] = {}
_SITE_TURN_MIN_INTERVAL = 1.0  # seconds between turns from one visitor session


@router.post("/concierge")
async def site_concierge(payload: ConciergePayload, db: DBSession = Depends(get_db)) -> dict:
    session = re.sub(r"[^A-Za-z0-9_-]", "", payload.session_id)[:64]
    if len(session) < 6:
        raise HTTPException(status_code=422, detail="invalid session id")
    now = time.monotonic()
    last = _last_site_turn.get(session)
    if last is not None and now - last < _SITE_TURN_MIN_INTERVAL:
        raise HTTPException(status_code=429, detail="please wait a moment before sending another message")
    if len(_last_site_turn) > 1000:
        _last_site_turn.clear()
    _last_site_turn[session] = now

    from app.agent import agent

    try:
        result = await agent.site_turn(
            db, wa_id=f"web-{session}", name=payload.name, text=payload.message)
    except Exception as exc:  # noqa: BLE001 — never 500 the chat away
        log.exception("concierge turn failed")
        raise HTTPException(status_code=503, detail=(
            "The assistant is temporarily unavailable. Please try again shortly, "
            "or book directly via the booking form or WhatsApp."))
    result["session_id"] = session
    return result
