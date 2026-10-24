"""WhatsApp channels API — the '+' button on the Connection tab.

  GET    /api/channels                      list channels (credentials masked)
  GET    /api/channels/meta                 wizard metadata (providers + fields)
  POST   /api/channels                      add a channel
  PATCH  /api/channels/{id}                 rename / creds / enable / disable
  DELETE /api/channels/{id}                 remove
  POST   /api/channels/{id}/test            real credential check via provider API
  POST   /api/channels/{id}/primary         make the command center
  GET/POST /api/channels/{id}/webhook       inbound webhook (verified, idempotent)
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from app.channels import (
    PROVIDER_FIELDS,
    PROVIDERS,
    PROVIDER_LABELS,
    create_channel,
    delete_channel,
    get_creds,
    list_channels,
    parse_webhook,
    provider_test,
    set_primary,
    set_status,
    update_channel,
    verify_signature,
)
from app.database import WebhookEvent, get_db

log = logging.getLogger("rental.api.channels")

router = APIRouter(prefix="/api/channels", tags=["Channels"])


class ChannelCreate(BaseModel):
    name: str = ""
    provider: str
    phone_number: str = ""
    credentials: dict = {}
    primary: bool = False


class ChannelUpdate(BaseModel):
    name: str | None = None
    phone_number: str | None = None
    credentials: dict | None = None
    enabled: bool | None = None


@router.get("/meta")
async def channels_meta() -> dict:
    return {
        "providers": [
            {"id": p, "label": PROVIDER_LABELS[p], "fields": PROVIDER_FIELDS[p]}
            for p in PROVIDERS
        ]
    }


@router.get("")
async def get_channels(db=Depends(get_db)) -> dict:
    return {"channels": list_channels(db)}


@router.post("")
async def add_channel(payload: ChannelCreate, db=Depends(get_db)) -> dict:
    if payload.provider not in PROVIDERS:
        raise HTTPException(status_code=422, detail=f"unknown provider '{payload.provider}'")
    if payload.primary:
        # first channel becomes primary automatically when none exists
        existing = list_channels(db)
        if not any(c["is_primary"] for c in existing):
            payload.primary = True
    try:
        row = create_channel(
            db, name=payload.name, provider=payload.provider,
            phone_number=payload.phone_number, credentials=payload.credentials,
            primary=payload.primary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"status": "created", "channel": row}


@router.patch("/{channel_id}")
async def patch_channel(channel_id: str, payload: ChannelUpdate, db=Depends(get_db)) -> dict:
    try:
        row = update_channel(
            db, channel_id, name=payload.name, phone_number=payload.phone_number,
            credentials=payload.credentials, enabled=payload.enabled,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="channel not found")
    return {"status": "updated", "channel": row}


@router.delete("/{channel_id}")
async def remove_channel(channel_id: str, db=Depends(get_db)) -> dict:
    try:
        delete_channel(db, channel_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="channel not found")
    return {"status": "deleted"}


@router.post("/{channel_id}/test")
async def test_channel(channel_id: str, db=Depends(get_db)) -> dict:
    row, creds = get_creds(db, channel_id)
    if not row:
        raise HTTPException(status_code=404, detail="channel not found")
    result = await provider_test(row["provider"], creds)
    set_status(db, channel_id, "connected" if result.get("ok") else "error",
               "" if result.get("ok") else result.get("error", ""))
    return {"channel_id": channel_id, **result}


@router.post("/{channel_id}/primary")
async def make_primary(channel_id: str, db=Depends(get_db)) -> dict:
    try:
        row = set_primary(db, channel_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="channel not found")
    return {"status": "primary", "channel": row}


@router.get("/{channel_id}/webhook")
async def channel_webhook_verify(channel_id: str, request: Request, db=Depends(get_db)) -> dict:
    row, creds = get_creds(db, channel_id)
    if not row:
        raise HTTPException(status_code=404, detail="channel not found")
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and row["provider"] in ("meta", "kapso"):
        token = params.get("hub.verify_token", "")
        if token and creds.get("verify_token") and token == creds.get("verify_token"):
            return int(params.get("hub.challenge", "0"))  # type: ignore[return-value]
        if row["provider"] == "meta":
            raise HTTPException(status_code=403, detail="verification failed")
    return {"status": "ok", "channel": channel_id}


@router.post("/{channel_id}/webhook")
async def channel_webhook(channel_id: str, request: Request, background: BackgroundTasks, db=Depends(get_db)) -> dict:
    row, creds = get_creds(db, channel_id)
    if not row:
        raise HTTPException(status_code=404, detail="channel not found")
    if not row["enabled"]:
        return {"status": "ignored", "reason": "channel disabled"}
    if not row["is_primary"]:
        # Secondary channels are configuration-only until explicitly promoted;
        # acknowledging them without routing prevents cross-channel replies.
        return {"status": "ignored", "reason": "channel is not primary"}

    raw = await request.body()
    sig = (
        request.headers.get("x-webhook-signature")
        or request.headers.get("X-Hub-Signature-256")
        or request.headers.get("X-Twilio-Signature")
    )
    if not verify_signature(row["provider"], creds, raw, sig, url=str(request.url)):
        log.warning("channel %s webhook rejected: bad signature", channel_id)
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    try:
        if row["provider"] == "twilio":
            from urllib.parse import parse_qsl
            payload = dict(parse_qsl(raw.decode("utf-8"), keep_blank_values=True))
        else:
            payload = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid webhook body")

    messages = parse_webhook(row["provider"], creds, payload)
    for inbound in messages:
        inbound.channel_id = channel_id
    # audit log
    db.add(WebhookEvent(
        provider=row["provider"], event_type="channel_message",
        message_id=",".join(m.message_id for m in messages)[:80],
        payload_json=raw.decode("utf-8", errors="replace")[:20000],
        processed=bool(messages),
    ))
    db.commit()

    if not messages:
        return {"status": "ignored", "reason": "no inbound message"}

    async def dispatch() -> None:
        from app.agent import agent

        for inbound in messages:
            await agent.handle_inbound(inbound)

    background.add_task(dispatch)
    return {"status": "accepted", "messages": len(messages)}
