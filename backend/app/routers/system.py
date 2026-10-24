"""System endpoints: health, stats, LLM chain status, Kapso connection state."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from app.config import PUBLIC_BASE_URL, llm_configured
from app.database import (
    Booking,
    Conversation,
    Customer,
    FAQ,
    KnowledgeDoc,
    Message,
    Vehicle,
    get_db,
)
from app.kapso import kapso
from app.llm import health_snapshot

log = logging.getLogger("zoomride.api.system")

router = APIRouter()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/health")
async def health(db: DBSession = Depends(get_db)) -> dict:
    """Backend liveness + configuration snapshot (real state, no fake ok)."""
    kapso_state = kapso.status_snapshot()
    return {
        "status": "ok",
        "time": _utcnow_iso(),
        "kapso": kapso_state,
        "llm_configured": llm_configured(),
        "counts": {
            "customers": db.scalar(select(func.count(Customer.id))) or 0,
            "conversations": db.scalar(select(func.count(Conversation.id))) or 0,
            "messages": db.scalar(select(func.count(Message.id))) or 0,
            "documents": db.scalar(select(func.count(KnowledgeDoc.id))) or 0,
            "faqs": db.scalar(select(func.count(FAQ.id))) or 0,
            "vehicles": db.scalar(select(func.count(Vehicle.id))) or 0,
            "bookings": db.scalar(select(func.count(Booking.id))) or 0,
        },
    }


@router.get("/connection")
async def connection_state(db: DBSession = Depends(get_db)) -> dict:
    """Live Kapso connection info for the Connection page.

    credential_state is computed from what is actually configured; verify calls
    the Kapso platform API and reports the REAL result (ok or failure reason).
    """
    creds_ok = bool(kapso.api_key and kapso.phone_number_id)
    state: dict = {
        "provider": "kapso",
        "credential_state": "configured" if creds_ok else "missing_credentials",
        "credentials": kapso.status_snapshot(),
        "verified": False,
        "connected": False,
        "detail": "",
        "error": "",
        "checked_at": None,
        "webhook_url": f"{PUBLIC_BASE_URL}/api/whatsapp/webhook",
        "note": (
            "Register this URL as the Kapso WhatsApp webhook (kind 'kapso', event "
            "whatsapp.message.received) in app.kapso.ai — PUBLIC_BASE_URL must be a "
            "public HTTPS address (use a tunnel for local dev), or rely on the "
            "built-in poller which needs no public URL."
        ),
    }
    if not creds_ok:
        state["error"] = "KAPSO_API_KEY / KAPSO_PHONE_NUMBER_ID missing in backend/.env"
        return state
    result = await kapso.verify_credentials()
    state["verified"] = bool(result.get("ok"))
    state["connected"] = bool(result.get("ok"))
    state["detail"] = str(result.get("detail") or "")
    state["error"] = str(result.get("error") or "")
    state["checked_at"] = _utcnow_iso()
    if result.get("phone_number"):
        state["phone_number"] = result["phone_number"]
    return state


@router.get("/llm/health")
async def llm_health() -> dict:
    """Per-provider chain state (never exposes keys)."""
    return health_snapshot()


@router.get("/stats")
async def stats(db: DBSession = Depends(get_db)) -> dict:
    """Console dashboard numbers — all computed live from the database."""
    total_convos = db.scalar(select(func.count(Conversation.id))) or 0
    handoffs = db.scalar(
        select(func.count(Conversation.id)).where(Conversation.status == "paused")
    ) or 0
    inbound = db.scalar(
        select(func.count(Message.id)).where(Message.direction == "in")
    ) or 0
    outbound = db.scalar(
        select(func.count(Message.id)).where(Message.direction == "out")
    ) or 0
    failed = db.scalar(
        select(func.count(Message.id)).where(
            Message.direction == "out", Message.status == "failed"
        )
    ) or 0
    intents_rows = db.execute(
        select(Message.intent, func.count(Message.id))
        .where(Message.direction == "out", Message.intent != "")
        .group_by(Message.intent)
    ).all()
    bookings_total = db.scalar(select(func.count(Booking.id))) or 0
    bookings_confirmed = db.scalar(
        select(func.count(Booking.id)).where(Booking.status == "confirmed")
    ) or 0
    bookings_active = db.scalar(
        select(func.count(Booking.id)).where(
            Booking.status.in_(("confirmed", "active"))
        )
    ) or 0
    confirmed_value = db.scalar(
        select(func.coalesce(func.sum(Booking.total_estimate), 0)).where(
            Booking.status.in_(("confirmed", "active"))
        )
    ) or 0
    recent = db.execute(
        select(Booking).where(Booking.status != "draft")
        .order_by(Booking.created_at.desc()).limit(5)
    ).scalars().all()
    vehicle_names = {
        v.id: v.name
        for v in db.execute(
            select(Vehicle).where(Vehicle.id.in_({b.vehicle_id for b in recent}))
        ).scalars().all()
    } if recent else {}
    return {
        "customers": db.scalar(select(func.count(Customer.id))) or 0,
        "conversations": total_convos,
        "handoffs_pending": handoffs,
        "messages_in": inbound,
        "messages_out": outbound,
        "messages_failed": failed,
        "documents": db.scalar(select(func.count(KnowledgeDoc.id))) or 0,
        "vehicles": db.scalar(select(func.count(Vehicle.id))) or 0,
        "bookings_total": bookings_total,
        "bookings_confirmed": bookings_confirmed,
        "bookings_active": bookings_active,
        "active_booking_value": float(confirmed_value or 0),
        "recent_bookings": [
            {
                "reference": row.reference or "",
                "status": row.status,
                "vehicle": vehicle_names.get(row.vehicle_id, ""),
                "total": float(row.total_estimate or 0),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in recent
        ],
        "intents": [
            {"intent": intent or "UNKNOWN", "count": count} for intent, count in intents_rows
        ],
    }
