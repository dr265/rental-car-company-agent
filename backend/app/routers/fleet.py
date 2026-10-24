"""Fleet + bookings API for the owner console.

  GET    /api/vehicles              list the fleet (grounding source of truth)
  POST   /api/vehicles              create / update one vehicle (upsert by code)
  PATCH  /api/vehicles/{code}       partial update (only supplied fields change)
  DELETE /api/vehicles/{code}       remove (refused while a booking is active)
  POST   /api/vehicles/import       bulk import from a CSV/XLSX catalogue file
  GET    /api/bookings              owner view of reservations (joined rows)
  POST   /api/bookings/{id}/cancel  staff-side cancel (any time, with audit)

Mutating endpoints honour ADMIN_AUTH_REQUIRED/ADMIN_API_TOKEN when enabled —
the console stays open on localhost for development, exactly like the rest of
the platform. The fleet table is the agent's ONLY source of truth for
availability and prices: nothing here invents data.
"""
from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.bookings import booking_summary, cancel
from app.database import Booking, Customer, Vehicle, get_db
from app.vehicles import delete_vehicle, list_vehicles, upsert_vehicle

log = logging.getLogger("rental.api.fleet")

router = APIRouter(tags=["Fleet"])


def require_admin(request: Request) -> None:
    """Optional admin guard (off by default for local development)."""
    from app.config import ADMIN_API_TOKEN, ADMIN_AUTH_REQUIRED

    if not ADMIN_AUTH_REQUIRED:
        return
    provided = request.headers.get("x-admin-token", "")
    if not ADMIN_API_TOKEN or provided != ADMIN_API_TOKEN:
        raise HTTPException(status_code=401, detail="admin token required")


class VehiclePayload(BaseModel):
    code: str
    name: str = ""
    category: str | None = None
    transmission: str | None = None
    fuel: str | None = None
    seats: int | None = None
    price_per_day: float | None = None
    price_per_hour: float | None = None
    deposit: float | None = None
    driver_fee_per_day: float | None = None
    mileage_limit_per_day: float | None = None
    extra_km_charge: float | None = None
    available: bool | None = None
    image_url: str | None = None
    description: str | None = None
    location: str | None = None


def _fields_from(payload: VehiclePayload) -> dict:
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="name is required")
    fields: dict = {"name": payload.name}
    for key in (
        "category", "transmission", "fuel", "seats", "price_per_day",
        "price_per_hour", "deposit", "driver_fee_per_day", "mileage_limit_per_day",
        "extra_km_charge", "image_url", "description", "location",
    ):
        value = getattr(payload, key)
        if value is not None:
            fields[key] = value
    if payload.available is not None:
        fields["available"] = 1 if payload.available else 0
    return fields


@router.get("/api/vehicles")
async def get_vehicles(db: DBSession = Depends(get_db)) -> dict:
    return {"vehicles": list_vehicles(db)}


@router.post("/api/vehicles")
async def create_vehicle(
    payload: VehiclePayload, request: Request, db: DBSession = Depends(get_db)
) -> dict:
    require_admin(request)
    try:
        row = upsert_vehicle(db, code=payload.code, **_fields_from(payload))
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"status": "saved", "code": row.code}


@router.patch("/api/vehicles/{code}")
async def patch_vehicle(
    code: str, payload: VehiclePayload, request: Request,
    db: DBSession = Depends(get_db),
) -> dict:
    require_admin(request)
    try:
        row = upsert_vehicle(db, code=code, **_fields_from(payload))
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"status": "saved", "code": row.code}


@router.delete("/api/vehicles/{code}")
async def remove_vehicle(
    code: str, request: Request, db: DBSession = Depends(get_db)
) -> dict:
    require_admin(request)
    try:
        if not delete_vehicle(db, code):
            raise HTTPException(status_code=404, detail="vehicle not found")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"status": "deleted", "code": code.upper()}


# --------------------------------------------------------------------------- #
# bulk import (CSV / XLSX catalogue)
# --------------------------------------------------------------------------- #
_NUMERIC_FIELDS = {
    "seats", "price_per_day", "price_per_hour", "deposit",
    "driver_fee_per_day", "mileage_limit_per_day", "extra_km_charge",
}
_TEXT_FIELDS = {
    "category", "transmission", "fuel", "image_url", "description", "location",
    "name", "code",
}
_BOOL_FIELDS = {"available"}


def _parse_number(raw) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(str(raw).replace(",", "").replace("₹", "").strip())
    except ValueError:
        return None


def _parse_bool(raw) -> int | None:
    if raw is None or str(raw).strip() == "":
        return None
    low = str(raw).strip().lower()
    if low in {"1", "true", "yes", "y", "available"}:
        return 1
    if low in {"0", "false", "no", "n", "unavailable", "parked"}:
        return 0
    return None


def _rows_from_csv(data: bytes) -> list[dict]:
    text = data.decode("utf-8-sig", errors="replace")
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def _rows_from_xlsx(data: bytes) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    rows: list[dict] = []
    for sheet in wb.worksheets:
        iterator = sheet.iter_rows(values_only=True)
        header: list[str] | None = None
        for row in iterator:
            cells = ["" if c is None else str(c).strip() for c in row]
            if not any(cells):
                continue
            if header is None:
                header = [c.lower().strip() for c in cells]
                continue
            rows.append({h: v for h, v in zip(header, cells) if h})
    wb.close()
    return rows


@router.post("/api/vehicles/import")
async def import_vehicles(
    request: Request, file: UploadFile = File(...), db: DBSession = Depends(get_db)
) -> dict:
    """Import a catalogue file. Columns (any order, case-insensitive):
    code, name, category, transmission, fuel, seats, price_per_day, deposit,
    driver_fee_per_day, mileage_limit_per_day, extra_km_charge, available,
    image_url, description, location. `code` + `name` are required per row."""
    require_admin(request)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    filename = (file.filename or "").lower()
    try:
        if filename.endswith((".xlsx", ".xlsm")):
            rows = _rows_from_xlsx(data)
        else:
            rows = _rows_from_csv(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"could not parse file: {exc}")
    saved, errors = 0, []
    for i, row in enumerate(rows, 2):
        code = str(row.get("code") or row.get("sku") or "").strip()
        name = str(row.get("name") or row.get("model") or "").strip()
        if not code or not name:
            errors.append(f"row {i}: code and name are required")
            continue
        fields: dict = {"name": name}
        for key in _TEXT_FIELDS:
            if key in ("name", "code"):
                continue
            if row.get(key) not in (None, ""):
                fields[key] = str(row[key]).strip()
        for key in _NUMERIC_FIELDS:
            value = _parse_number(row.get(key))
            if value is not None:
                fields[key] = value
        flag = _parse_bool(row.get("available"))
        if flag is not None:
            fields["available"] = flag
        try:
            upsert_vehicle(db, code=code, **fields)
            saved += 1
        except ValueError as exc:
            errors.append(f"row {i}: {exc}")
    db.commit()
    return {"status": "imported", "saved": saved, "errors": errors[:20]}


# --------------------------------------------------------------------------- #
# owner booking view
# --------------------------------------------------------------------------- #
def _booking_dict(db: DBSession, b: Booking) -> dict:
    vehicle = db.get(Vehicle, b.vehicle_id)
    customer = db.get(Customer, b.customer_id)
    return {
        "id": b.id,
        "reference": b.reference or "",
        "status": b.status,
        "customer": (customer.whatsapp_name or customer.name or "") if customer else "",
        "customer_phone": (customer.display_phone or f"+{customer.phone}") if customer else "",
        "vehicle": vehicle.name if vehicle else "",
        "vehicle_code": vehicle.code if vehicle else "",
        "start_at": b.start_at.isoformat() if b.start_at else None,
        "end_at": b.end_at.isoformat() if b.end_at else None,
        "days": b.days,
        "with_driver": bool(b.with_driver),
        "total_estimate": b.total_estimate,
        "deposit": b.deposit,
        "currency": b.currency,
        "pickup_location": b.pickup_location or "",
        "summary": booking_summary(b, vehicle),
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


@router.get("/api/bookings")
async def get_bookings(
    status: str = "", db: DBSession = Depends(get_db)
) -> dict:
    stmt = select(Booking).order_by(Booking.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(Booking.status == status)
    rows = db.execute(stmt).scalars().all()
    return {"bookings": [_booking_dict(db, b) for b in rows]}


@router.post("/api/bookings/{booking_id}/cancel")
async def staff_cancel(
    booking_id: str, request: Request, db: DBSession = Depends(get_db)
) -> dict:
    """Staff-side cancel: allowed even after the rental started (the customer
    path is stricter). Records the real outcome — never a fake success."""
    require_admin(request)
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="booking not found")
    ok, reason = cancel(db, booking, by_customer=False)
    return {"status": "cancelled" if ok else "not_cancelled", "reason": reason,
            "reference": booking.reference}
