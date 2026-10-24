"""Owner Chat API: real conversation management for the console.

  GET    /api/conversations                 list (search, unread, status filter)
  GET    /api/conversations/{id}            customer context + memory + messages
  POST   /api/conversations/{id}/reply      owner human reply (pauses the agent)
  POST   /api/conversations/{id}/resume     hand the chat back to the agent
  POST   /api/conversations/{id}/read       clear unread counter
  GET    /api/conversations/{id}/language   active conversation language
  PUT    /api/conversations/{id}/language   switch it (whole conversation)
  POST   /api/conversations/{id}/reset      clear the thread + un-pause the agent
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete as sa_delete, func, or_, select
from sqlalchemy.orm import Session as DBSession

from app.agent import agent
from app.config import HANDOFF_AUTO_RESUME_MINUTES
from app.database import Conversation, Customer, CustomerMemory, Message, get_db
from app.languages import (
    EXPLICIT_SOURCE,
    SUPPORTED as SUPPORTED_LANGUAGES,
    get_language,
    get_language_source,
    language_options,
    set_language,
    switch_confirm,
)

router = APIRouter(prefix="/api/conversations", tags=["Owner Chat"])


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _conv_dict(db: DBSession, c: Conversation, customer: Customer | None) -> dict:
    if customer is None:
        customer = db.get(Customer, c.customer_id)
    return {
        "id": c.id,
        "customer_id": c.customer_id,
        "customer_name": (customer.whatsapp_name or customer.name or "") if customer else "",
        "display_phone": (customer.display_phone or f"+{customer.phone}") if customer else "",
        "status": c.status,
        # when the chat was handed to staff (drives the auto-resume hint)
        "paused_at": _iso(c.paused_at),
        "handoff_reason": c.handoff_reason or "",
        "handoff_at": _iso(c.handoff_at),
        "language": get_language(db, c.customer_id) or "",
        "language_source": get_language_source(db, c.customer_id),
        "unread_count": c.unread_count or 0,
        "summary": c.summary or "",
        "last_message_at": _iso(c.last_message_at),
        "last_message_preview": c.last_message_preview or "",
        "created_at": _iso(c.created_at),
    }


@router.get("")
async def list_conversations(
    q: str = Query(default="", max_length=120),
    status: str = Query(default="", pattern="^(|running|paused|closed)$"),
    limit: int = Query(default=100, ge=1, le=200),
    db: DBSession = Depends(get_db),
) -> dict:
    """WhatsApp conversations, filtered before pagination and search limiting."""
    stmt = (
        select(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .where(
            # 'whatsapp' = env Kapso transport, 'w:<channel_id>' = added primary
            # channels (app/channels.py). Both are customer-facing chats; the
            # console tester uses channel='simulator' and stays out of the inbox.
            or_(
                Conversation.channel.like("whatsapp%"),
                Conversation.channel.like("w:%"),
            )
        )
    )
    if status:
        stmt = stmt.where(Conversation.status == status)
    needle = q.strip()
    if needle:
        pattern = f"%{needle}%"
        stmt = stmt.where(or_(
            Conversation.last_message_preview.ilike(pattern),
            Customer.whatsapp_name.ilike(pattern),
            Customer.name.ilike(pattern),
            Customer.phone.ilike(pattern),
            Customer.notes.ilike(pattern),
        ))
    stmt = stmt.order_by(Conversation.last_message_at.desc()).limit(limit)
    convs = db.execute(stmt).scalars().all()
    return {
        "conversations": [_conv_dict(db, c, None) for c in convs],
        # a paused chat is released to the agent after this many minutes with no
        # staff reply, so nothing can stay stuck in 'WITH STAFF' forever
        "auto_resume_minutes": HANDOFF_AUTO_RESUME_MINUTES,
    }


@router.post("/resume-all")
async def resume_all(db: DBSession = Depends(get_db)) -> dict:
    """Give every paused chat back to the AI agent (bulk un-stick)."""
    count = await agent.resume_all(db)
    return {"status": "running", "resumed": count}


@router.get("/{conversation_id}")
async def conversation_detail(conversation_id: str, db: DBSession = Depends(get_db)) -> dict:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    customer = db.get(Customer, conv.customer_id)
    messages = db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc())
    ).scalars().all()
    memories = db.execute(
        select(CustomerMemory)
        .where(CustomerMemory.customer_id == conv.customer_id)
        .order_by(CustomerMemory.updated_at.desc())
    ).scalars().all()
    return {
        "conversation": _conv_dict(db, conv, customer),
        "customer": {
            "id": customer.id,
            "name": customer.name or "",
            "whatsapp_name": customer.whatsapp_name or "",
            "display_phone": customer.display_phone or f"+{customer.phone}",
            "first_seen_at": _iso(customer.first_seen_at),
            "last_seen_at": _iso(customer.last_seen_at),
            "notes": customer.notes or "",
        } if customer else None,
        "memory": [
            {"key": m.key, "value": m.value, "source": m.source, "updated_at": _iso(m.updated_at)}
            for m in memories
        ],
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "sender": m.sender,
                "body": m.body,
                "msg_type": m.msg_type,
                "image_url": m.image_url or "",
                "status": m.status,
                "intent": m.intent,
                "error": m.error_detail or "",
                "created_at": _iso(m.created_at),
            }
            for m in messages
        ],
    }


class ReplyPayload(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    # Optional public image link: lets the owner send a product photo from the
    # console without pasting a URL into the message text.
    image_url: str = Field(default="", max_length=500)
    # Optional registry/upload id (the console's attach-image button). This is
    # the portable way: the file is already stored under the media directory and
    # is delivered as an ACTUAL image, not a path.
    media_id: str = Field(default="", max_length=80)

    @field_validator("text")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value

    @field_validator("image_url")
    @classmethod
    def public_link(cls, value: str) -> str:
        value = (value or "").strip()
        if value and not value.lower().startswith(("http://", "https://")):
            raise ValueError("image_url must be a public http(s) link")
        return value


@router.post("/{conversation_id}/reply")
async def reply(conversation_id: str, payload: ReplyPayload, db: DBSession = Depends(get_db)) -> dict:
    """Send a human reply from the console; the agent pauses for this chat."""
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    try:
        msg = await agent.send_human_message(db, conversation_id, payload.text.strip(),
                                              image_url=payload.image_url.strip(),
                                              image_id=payload.media_id.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"status": msg.status, "error": msg.error_detail, "message_id": msg.id,
            "conversation_status": conv.status}


@router.post("/{conversation_id}/resume")
async def resume(conversation_id: str, db: DBSession = Depends(get_db)) -> dict:
    """Give the chat back to the AI agent."""
    try:
        await agent.resume_agent(db, conversation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"status": "running"}


@router.post("/{conversation_id}/read")
async def mark_read(conversation_id: str, db: DBSession = Depends(get_db)) -> dict:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    conv.unread_count = 0
    db.commit()
    return {"status": "ok"}


class LanguagePayload(BaseModel):
    language: str = Field(min_length=2, max_length=8)

    @field_validator("language")
    @classmethod
    def known(cls, value: str) -> str:
        code = value.strip().lower()
        if code not in SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported language {value!r}")
        return code


@router.get("/{conversation_id}/language")
async def get_conversation_language(conversation_id: str, db: DBSession = Depends(get_db)) -> dict:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {
        "language": get_language(db, conv.customer_id) or "",
        "source": get_language_source(db, conv.customer_id),
        "supported": language_options(),
    }


@router.put("/{conversation_id}/language")
async def set_conversation_language(
    conversation_id: str, payload: LanguagePayload, db: DBSession = Depends(get_db)
) -> dict:
    """Switch the active language for the WHOLE conversation.

    Only the language fact changes — history, memory, persona, tools and the
    conversation itself are untouched, so the customer keeps full context.
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    set_language(db, conv.customer_id, payload.language, source=EXPLICIT_SOURCE)
    db.commit()
    return {
        "status": "updated",
        "language": payload.language,
        "confirm": switch_confirm(payload.language),
    }


@router.post("/{conversation_id}/reset")
async def reset_conversation(
    conversation_id: str, clear_memory: bool = Query(default=False),
    db: DBSession = Depends(get_db),
) -> dict:
    """Start this chat fresh: clear the thread and hand it back to the agent.

    Used when a chat got stuck (e.g. the agent escalated to staff and stayed
    paused). The conversation is set back to 'running' so replies resume; pass
    clear_memory=true to also drop the learned customer facts.
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    removed = db.scalar(
        select(func.count(Message.id)).where(Message.conversation_id == conv.id)
    ) or 0
    db.execute(sa_delete(Message).where(Message.conversation_id == conv.id))
    conv.status = "running"
    conv.unread_count = 0
    conv.summary = ""
    conv.last_message_preview = ""
    if clear_memory:
        db.execute(sa_delete(CustomerMemory).where(
            CustomerMemory.customer_id == conv.customer_id))
    db.commit()
    return {
        "status": "reset",
        "removed_messages": removed,
        "conversation_status": conv.status,
        "memory_cleared": bool(clear_memory),
    }
