"""Owner console assistant: answers the fleet owner's questions using ONLY live
backend data (fleet, bookings, customers, conversations, memory, shop settings
and knowledge base). Read-only — it never invents data and cannot send messages.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from app.database import (
    Booking,
    Conversation,
    Customer,
    CustomerMemory,
    FAQ,
    KnowledgeDoc,
    Message,
    Vehicle,
    get_db,
)
from app.llm import chat_json
from app.persona import get_persona

router = APIRouter(prefix="/api/owner", tags=["Owner Assistant"])


class OwnerAsk(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _business_snapshot(db: DBSession) -> str:
    """Everything the owner-assistant may truthfully say, as compact facts."""
    now = datetime.now(timezone.utc)

    total_customers = db.scalar(select(func.count(Customer.id))) or 0
    total_convos = db.scalar(select(func.count(Conversation.id))) or 0
    paused = db.scalar(
        select(func.count(Conversation.id)).where(Conversation.status == "paused")
    ) or 0
    total_msgs = db.scalar(select(func.count(Message.id))) or 0
    in_msgs = db.scalar(
        select(func.count(Message.id)).where(Message.direction == "in")
    ) or 0
    failed = db.scalar(
        select(func.count(Message.id)).where(
            Message.direction == "out", Message.status == "failed"
        )
    ) or 0
    docs = db.scalar(select(func.count(KnowledgeDoc.id))) or 0
    faqs = db.scalar(select(func.count(FAQ.id))) or 0
    vehicles = db.scalar(select(func.count(Vehicle.id))) or 0
    bookings_total = db.scalar(select(func.count(Booking.id))) or 0
    bookings_confirmed = db.scalar(
        select(func.count(Booking.id)).where(Booking.status == "confirmed")
    ) or 0
    bookings_active = db.scalar(
        select(func.count(Booking.id)).where(
            Booking.status.in_(("confirmed", "active"))
        )
    ) or 0

    recent = db.execute(
        select(Customer).order_by(Customer.last_seen_at.desc()).limit(10)
    ).scalars().all()
    cust_ids = [c.id for c in recent]

    mem_by_cust: dict[str, list[str]] = {}
    conv_owner: dict[str, str] = {}
    last_in_by_cust: dict[str, datetime] = {}
    if cust_ids:
        for m in db.execute(
            select(CustomerMemory)
            .where(CustomerMemory.customer_id.in_(cust_ids))
            .order_by(CustomerMemory.updated_at.desc())
        ).scalars().all():
            mem_by_cust.setdefault(m.customer_id, []).append(f"{m.key}={m.value}")

        conv_owner = dict(db.execute(
            select(Conversation.id, Conversation.customer_id)
            .where(Conversation.customer_id.in_(cust_ids))
        ).all())
        for conv_id, last_at in db.execute(
            select(Message.conversation_id, func.max(Message.created_at))
            .where(Message.conversation_id.in_(list(conv_owner)),
                   Message.direction == "in")
            .group_by(Message.conversation_id)
        ).all():
            owner_id = conv_owner.get(conv_id)
            if owner_id is None or last_at is None:
                continue
            prev = last_in_by_cust.get(owner_id)
            if prev is None or last_at > prev:
                last_in_by_cust[owner_id] = last_at

    cust_lines = []
    for c in recent:
        mem = ", ".join(mem_by_cust.get(c.id, [])[:6])
        last_in = last_in_by_cust.get(c.id)
        cust_lines.append(
            f"- {c.display_phone or c.phone}"
            f"{' (' + c.whatsapp_name + ')' if c.whatsapp_name else ''}"
            f" | last inbound: {last_in.isoformat() if last_in else 'never'}"
            f"{' | memory: ' + mem if mem else ''}"
        )

    vehicle_rows = db.execute(
        select(Vehicle).order_by(Vehicle.name).limit(40)
    ).scalars().all()
    vehicle_lines = []
    for v in vehicle_rows:
        rates = " / ".join(
            f"{h}h ₹{int(getattr(v, f'price_{h}h') or 0):,}"
            for h in (6, 12, 24) if getattr(v, f"price_{h}h", None)
        )
        vehicle_lines.append(
            f"- {v.code}: {v.name} | {v.category or 'uncategorised'} | "
            f"{'available' if v.available else 'UNAVAILABLE'} | "
            f"{rates or 'no packages'} | deposit ₹{int(v.deposit or 0):,}"
        )

    booking_rows = db.execute(
        select(Booking).order_by(Booking.created_at.desc()).limit(15)
    ).scalars().all()
    vehicle_name = {v.id: v.name for v in vehicle_rows}
    booking_lines = []
    booking_customer_ids = {b.customer_id for b in booking_rows}
    customer_name = {
        c.id: (c.whatsapp_name or c.display_phone or c.phone)
        for c in db.execute(
            select(Customer).where(Customer.id.in_(booking_customer_ids))
        ).scalars().all()
    } if booking_customer_ids else {}
    for b in booking_rows:
        start = b.start_at.strftime("%d %b %H:%M") if b.start_at else "?"
        end = b.end_at.strftime("%d %b %H:%M") if b.end_at else "?"
        booking_lines.append(
            f"- {b.reference or b.id}: {b.status} | "
            f"{vehicle_name.get(b.vehicle_id, b.vehicle_id)} | "
            f"{b.duration_hours or '?'}h | {b.drive_mode or 'self-drive'} | "
            f"{b.handover or 'hub'} | {start} → {end} | "
            f"₹{float(b.total_estimate or 0):,.0f} | "
            f"{customer_name.get(b.customer_id, 'customer')}"
        )

    docs_rows = db.execute(
        select(KnowledgeDoc).order_by(KnowledgeDoc.created_at.desc()).limit(10)
    ).scalars().all()
    doc_lines = [
        f"- {d.filename} ({d.status}, {d.chunk_count} chunks, {d.size} bytes)" for d in docs_rows
    ]

    persona = get_persona(db)
    return "\n".join([
        f"TIME NOW: {now.isoformat()}",
        f"PERSONA: business={persona.get('shop_name')}; assistant={persona.get('assistant_name')};"
        f" hours={persona.get('working_hours')}; contact={persona.get('contact_info') or 'n/a'}",
        f"COUNTS: customers={total_customers}; conversations={total_convos};"
        f" awaiting_human={paused}; messages={total_msgs} (in={in_msgs}); failed_sends={failed};"
        f" knowledge_docs={docs}; faqs={faqs}; vehicles={vehicles};"
        f" bookings={bookings_total} (confirmed={bookings_confirmed}, active={bookings_active})",
        "FLEET:",
        *(vehicle_lines or ["- (no vehicles configured)"]),
        "RECENT CUSTOMERS:",
        *(cust_lines or ["- (none yet)"]),
        "RECENT BOOKINGS (up to 15):",
        *(booking_lines or ["- (none yet)"]),
        "KNOWLEDGE DOCUMENTS:",
        *(doc_lines or ["- (none)"]),
    ])


OWNER_SYSTEM = """You are the fleet owner's console assistant for ZoomRideXX Car Rentals' WhatsApp agent.
Answer the owner's questions using ONLY the <business_snapshot> data provided.
You can summarise activity, list customers and what you know about them, report
fleet vehicles, package rates, deposits, bookings, shop rules and knowledge
documents, and explain configuration. If the data does not contain the answer,
say so plainly — never invent customers, vehicles, prices, availability, bookings
or events. Keep answers short (1-5 sentences or a compact list). Reply with one
JSON object: {"reply": "..."}."""


@router.post("")
async def owner_ask(payload: OwnerAsk, db: DBSession = Depends(get_db)) -> dict:
    snapshot = _business_snapshot(db)
    try:
        result = await chat_json(
            messages=[
                {"role": "system", "content": OWNER_SYSTEM + "\n\n<business_snapshot>\n" + snapshot + "\n</business_snapshot>"},
                {"role": "user", "content": payload.text},
            ],
            tier="light", max_tokens=500,
        )
        reply = str(result.get("reply") or "").strip()
        if not reply:
            raise RuntimeError("empty reply")
        return {"reply": reply}
    except Exception as exc:  # noqa: BLE001
        return {"reply": "", "error": f"Owner assistant unavailable: {exc}"}
