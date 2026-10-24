"""Kapso WhatsApp webhook + outbound test endpoints (env transport).

  GET  /api/whatsapp/webhook        Meta-style verification handshake (hub.challenge)
  POST /api/whatsapp/webhook        Kapso event deliveries (signature-verified)
  POST /api/whatsapp/register       one-click webhook registration via Kapso platform API
  POST /api/whatsapp/test-send      controlled outbound test message (integration testing)
  POST /api/whatsapp/simulate       console tester (same engine, no WhatsApp send)
  GET/POST /api/whatsapp/run|pause|run-state   global RUN/PAUSE switch

Webhook processing is idempotent: signature must match, messages are deduped
by WhatsApp message id (in-memory + cross-process claim), raw payloads are
archived for audit, and processing happens in a background task so Kapso
always gets a fast 200. Delivery-status events (sent/delivered/read/failed)
are recorded on the corresponding outbound Message rows — a 200 from the send
API is treated as "accepted", and only these callbacks upgrade it to
delivered/read.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent import SIMULATOR_WA_ID, agent
from app.database import Conversation, Customer, Message, SessionLocal, WebhookEvent
from app.kapso import describe_send_error, kapso

log = logging.getLogger("rental.api.whatsapp")

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])


@router.get("/webhook")
async def webhook_verify(request: Request) -> dict:
    """Meta-style subscription handshake (hub.mode/hub.verify_token/hub.challenge)."""
    params = request.query_params
    if params.get("hub.mode") == "subscribe":
        verify_token_value = params.get("hub.verify_token", "")
        if verify_token_value and kapso.webhook_secret and verify_token_value == kapso.webhook_secret:
            return int(params.get("hub.challenge", "0"))  # type: ignore[return-value]
        raise HTTPException(status_code=403, detail="verification failed")
    return {"status": "ok", "endpoint": "kapso webhook live"}


@router.post("/webhook")
async def webhook_receive(request: Request, background: BackgroundTasks) -> dict:
    """Receive Kapso webhook events.

    Security: X-Webhook-Signature must be a valid HMAC-SHA256 of the raw body
    using KAPSO_WEBHOOK_SECRET (fail-closed when the secret is unset).
    """
    raw = await request.body()
    signature = request.headers.get("x-webhook-signature") or request.headers.get("X-Webhook-Signature")
    if not kapso.verify_signature(raw, signature):
        log.warning("webhook rejected: bad/missing signature")
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid JSON payload")

    event_type = request.headers.get("x-webhook-event") or ""
    idem_key = request.headers.get("x-idempotency-key") or ""

    inbound_messages = kapso.parse_webhook(payload)
    status_events = kapso.parse_statuses(payload)
    message_ids = [m.message_id for m in inbound_messages]

    # archive for audit + duplicate protection (raw payload, nothing redacted)
    db = SessionLocal()
    try:
        db.add(WebhookEvent(
            provider="kapso",
            event_type=event_type or ("batch" if payload.get("batch") else "message"),
            message_id=(",".join(message_ids) or
                        ",".join(s["message_id"] for s in status_events))[:80],
            payload_json=raw.decode("utf-8", errors="replace")[:20000],
            processed=bool(inbound_messages or status_events),
        ))
        if status_events:
            # Delivery-status tracking: accepted (send API 200) → sent →
            # delivered → read; failed records the provider's complaint.
            _valid = {"sent", "delivered", "read", "failed"}
            for st in status_events:
                status = st["status"] if st["status"] in _valid else ""
                if not status:
                    continue
                row_id = db.execute(
                    select(Message.id).where(
                        Message.kapso_message_id == st["message_id"],
                        Message.direction == "out",
                    ).limit(1)
                ).scalar_one_or_none()
                if row_id is None:
                    continue
                db.execute(
                    Message.__table__.update()
                    .where(Message.id == row_id)
                    .values(status=status)
                )
        db.commit()
    finally:
        db.close()

    if not inbound_messages:
        if status_events:
            return {"status": "statuses_recorded", "count": len(status_events),
                    "idempotency_key": idem_key}
        return {"status": "ignored", "reason": "no inbound customer message in payload",
                "idempotency_key": idem_key}

    for inbound in inbound_messages:
        background.add_task(agent.handle_inbound, inbound)
    return {"status": "accepted", "messages": len(inbound_messages), "idempotency_key": idem_key}


# --------------------------------------------------------------------------- #
# webhook registration (one click instead of dashboard copy-paste)
# --------------------------------------------------------------------------- #
class RegisterPayload(BaseModel):
    url: str = Field(min_length=8)
    events: list[str] = Field(default_factory=lambda: ["whatsapp.message.received"])
    secret_key: str = ""  # optional override; defaults to env secret


@router.post("/register")
async def register_webhook(payload: RegisterPayload) -> dict:
    """Register this backend's URL with Kapso via their platform API."""
    if not kapso.api_key or not kapso.phone_number_id:
        raise HTTPException(status_code=422, detail="Kapso credentials missing in backend/.env")
    secret = payload.secret_key.strip() or kapso.webhook_secret
    if not secret:
        raise HTTPException(status_code=422, detail="webhook secret required (env or request)")
    body = {
        "whatsapp_webhook": {
            "kind": "kapso",
            "url": payload.url,
            "events": payload.events,
            "secret_key": secret,
            "active": True,
        }
    }
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.kapso.ai/platform/v1/whatsapp/phone_numbers/{kapso.phone_number_id}/webhooks",
                json=body,
                headers=kapso._headers(),  # transport's own auth headers (from env config)
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Kapso API unreachable: {exc}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code,
                            detail=f"Kapso webhook registration failed: {resp.text[:300]}")
    return {"status": "registered", "url": payload.url, "kapso_response": resp.json()}


class TestSendPayload(BaseModel):
    to: str = Field(min_length=8)
    text: str = Field(min_length=1, max_length=1000)


@router.post("/test-send")
async def test_send(payload: TestSendPayload) -> dict:
    """Send one controlled outbound message through the real Kapso API.

    Used to validate the integration (per the delivery checklist) — not wired
    to any production flow. Errors are returned as-is so failures are visible.
    """
    from app.kapso import normalize_phone

    wa = normalize_phone(payload.to)
    try:
        result = await kapso.send_text(wa, payload.text)
    except Exception as exc:  # noqa: BLE001
        # Report the REAL reason with a next step (e.g. a sandbox number's
        # recipient allowlist, or a closed 24-hour window) instead of a raw
        # provider body the owner cannot act on.
        raise HTTPException(status_code=502,
                            detail=f"Kapso send failed: {describe_send_error(exc)}")
    log.info("test WhatsApp message sent to …%s", wa[-4:])
    return {"status": "sent", "to_tail": f"…{wa[-4:]}", "kapso_message_id": result.get("message_id", "")}


# --------------------------------------------------------------------------- #
# outbound delivery diagnostics
# --------------------------------------------------------------------------- #
@router.get("/send-diagnostics")
async def send_diagnostics() -> dict:
    """Who actually receives replies? Per-recipient outbound outcome.

    Groups the outbound message log by customer and reports sent / delivered /
    read / failed counts plus the most recent recorded failure reason. This is
    the endpoint that turns "only my number gets answers" into a named cause:
    a recipient sitting at 0 sent with an allowlist error is a provider-side
    restriction, not an application bug. Read-only; never returns credentials.
    """
    from sqlalchemy import func, select

    db = SessionLocal()
    try:
        grouped = db.execute(
            select(
                Customer.phone,
                Customer.display_phone,
                Message.status,
                func.count(Message.id),
            )
            .join(Conversation, Message.conversation_id == Conversation.id)
            .join(Customer, Conversation.customer_id == Customer.id)
            .where(Message.direction == "out")
            .group_by(Customer.phone, Customer.display_phone, Message.status)
        ).all()

        recipients: dict[str, dict] = {}
        for phone, display, status, count in grouped:
            row = recipients.setdefault(
                phone,
                {"display_phone": display or f"+{phone}", "counts": {},
                 "attempts": 0, "delivered": 0, "failed": 0, "last_error": ""},
            )
            key = status or "unknown"
            row["counts"][key] = row["counts"].get(key, 0) + count
            row["attempts"] += count
            if key in {"delivered", "read"}:
                row["delivered"] += count
            if key in {"failed", "error"}:
                row["failed"] += count

        # Attach the most recent plain-text reason per failing recipient.
        for phone, row in recipients.items():
            if not row["attempts"] or row["delivered"]:
                continue
            last = db.execute(
                select(Message.error_detail)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .join(Customer, Conversation.customer_id == Customer.id)
                .where(Customer.phone == phone, Message.direction == "out",
                       Message.error_detail != "")
                .order_by(Message.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            row["last_error"] = describe_send_error(last or "")

        ordered = sorted(recipients.values(), key=lambda r: -r["attempts"])
        return {
            "transport": "kapso",
            "recipients": ordered[:50],
            "note": (
                "A recipient with attempts but zero delivered, whose last error "
                "names a sandbox allowlist or the 24-hour window, is being "
                "blocked by WhatsApp — not by this application."
            ),
        }
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# in-app simulator (console tester — same engine as WhatsApp, no WhatsApp send)
# --------------------------------------------------------------------------- #
class SimulatePayload(BaseModel):
    text: str = Field(default="", max_length=1000)
    button_id: str = Field(default="", max_length=64)


@router.post("/simulate")
async def simulate(payload: SimulatePayload) -> dict:
    """Run one agent turn for the console tester (no WhatsApp send).

    Delegates to the SAME brain the WhatsApp path uses (agent.simulate_turn):
    memory retrieval, fleet + knowledge grounding, persona, LLM, deterministic
    booking stages — so what the owner validates here is exactly what
    customers experience on WhatsApp.
    """
    if not payload.text.strip() and not payload.button_id.strip():
        raise HTTPException(status_code=422, detail="text or button_id is required")
    from app.database import SessionLocal as _DB

    db = _DB()
    try:
        return await agent.simulate_turn(db, payload.text, payload.button_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("simulate failed")
        raise HTTPException(status_code=500, detail=str(exc)[:300])
    finally:
        db.close()


@router.delete("/simulate")
async def simulate_reset() -> dict:
    """Clear the simulator conversation (real deletion from the database)."""
    from sqlalchemy import delete as sa_delete, select

    from app.database import Conversation, Customer

    db = SessionLocal()
    try:
        cust = db.execute(
            select(Customer).where(Customer.phone == SIMULATOR_WA_ID)
        ).scalar_one_or_none()
        if cust is None:
            return {"status": "reset"}
        convs = db.execute(
            select(Conversation).where(Conversation.customer_id == cust.id)
        ).scalars().all()
        for conv in convs:
            db.execute(sa_delete(Message).where(Message.conversation_id == conv.id))
            db.delete(conv)
        db.delete(cust)
        db.commit()
        return {"status": "reset"}
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# global run/pause
# --------------------------------------------------------------------------- #
@router.get("/run-state")
async def run_state() -> dict:
    from app.poller import agent_running

    return {"running": agent_running()}


@router.post("/run")
async def run_agent() -> dict:
    from app.poller import set_agent_running

    set_agent_running(True)
    return {"running": True}


@router.post("/pause")
async def pause_agent() -> dict:
    from app.poller import set_agent_running

    set_agent_running(False)
    return {"running": False}
