"""Multi-provider WhatsApp channels (the '+' button on the Connection tab).

Each channel row holds Fernet-encrypted credentials. Providers implement
test/send/verify/parse; the PRIMARY channel routes inbound messages to the
agent and carries outbound replies. Channels added here work alongside the
env-configured Kapso transport: inbound from any enabled primary channel is
dispatched to the same agent pipeline, and duplicate suppression happens at
the message-id level in the agent + poller.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.config import PUBLIC_BASE_URL
from app.crypto import decrypt_json, encrypt_json
from app.database import Channel, SessionLocal

log = logging.getLogger("rental.channels")

PROVIDERS = ("kapso", "meta", "generic", "twilio")
PROVIDER_LABELS = {
    "kapso": "Kapso (WhatsApp Cloud API compatible)",
    "meta": "Meta WhatsApp Cloud API",
    "generic": "Generic webhook / API",
    "twilio": "Twilio WhatsApp",
}
PROVIDER_FIELDS: dict[str, list[str]] = {
    "kapso": ["api_key", "phone_number_id", "webhook_secret"],
    "meta": ["access_token", "phone_number_id", "verify_token", "app_secret"],
    "generic": ["send_url", "send_bearer_token", "secret_header", "webhook_secret"],
    "twilio": ["account_sid", "auth_token", "phone_number"],
}


def normalize_phone(raw: str | None) -> str:
    return re.sub(r"\D", "", str(raw or ""))


@dataclass
class Inbound:
    message_id: str
    wa_id: str
    text: str
    msg_type: str = "text"
    sender_name: str = ""
    channel_id: str = ""
    # the agent's dedupe/persistence reads this; keep it compatible with
    # app.kapso.InboundMessage
    conversation_id: str = ""

    @property
    def display_number(self) -> str:
        return f"+{self.wa_id}" if self.wa_id else ""


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #
def list_channels(db: DBSession) -> list[dict]:
    rows = db.execute(select(Channel).order_by(Channel.created_at)).scalars().all()
    return [_row_dict(r) for r in rows]


def _row_dict(r: Channel) -> dict:
    creds = decrypt_json(r.credentials_enc)
    return {
        "id": r.id,
        "name": r.name,
        "provider": r.provider,
        "phone_number": r.phone_number or "",
        "status": r.status,
        "enabled": bool(r.enabled),
        "is_primary": bool(r.is_primary),
        "last_error": r.last_error or "",
        "last_checked_at": r.last_checked_at.isoformat() if r.last_checked_at else None,
        "credentials_set": sorted(creds.keys()),
        "webhook_url": f"/api/channels/{r.id}/webhook",
        "webhook_absolute_url": f"{PUBLIC_BASE_URL}/api/channels/{r.id}/webhook",
    }


def get_channel(db: DBSession, channel_id: str) -> Channel | None:
    return db.get(Channel, channel_id)


def get_creds(db: DBSession, channel_id: str) -> tuple[dict, dict]:
    row = db.get(Channel, channel_id)
    if row is None:
        return {}, {}
    return _row_dict(row), decrypt_json(row.credentials_enc)


def create_channel(
    db: DBSession, *, name: str, provider: str, phone_number: str = "",
    credentials: dict | None = None, primary: bool = False,
) -> dict:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider '{provider}' (choose from {', '.join(PROVIDERS)})")
    if primary:
        for r in db.execute(select(Channel)).scalars().all():
            r.is_primary = 0
    row = Channel(
        name=(name or PROVIDER_LABELS.get(provider, provider)).strip()[:120],
        provider=provider,
        phone_number=normalize_phone(phone_number),
        credentials_enc=encrypt_json(credentials or {}),
        is_primary=1 if primary else 0,
    )
    db.add(row)
    db.commit()
    return _row_dict(row)


def update_channel(
    db: DBSession, channel_id: str, *, name: str | None = None,
    phone_number: str | None = None, credentials: dict | None = None,
    enabled: bool | None = None,
) -> dict:
    row = db.get(Channel, channel_id)
    if row is None:
        raise KeyError("channel not found")
    if name is not None:
        row.name = name.strip()[:120]
    if phone_number is not None:
        row.phone_number = normalize_phone(phone_number)
    if credentials:
        merged = decrypt_json(row.credentials_enc)
        merged.update({k: v for k, v in credentials.items() if v not in (None, "")})
        row.credentials_enc = encrypt_json(merged)
    if enabled is not None:
        row.enabled = 1 if enabled else 0
    db.commit()
    return _row_dict(row)


def set_primary(db: DBSession, channel_id: str) -> dict:
    row = db.get(Channel, channel_id)
    if row is None:
        raise KeyError("channel not found")
    for r in db.execute(select(Channel)).scalars().all():
        r.is_primary = 0
    row.is_primary = 1
    row.enabled = 1
    db.commit()
    return _row_dict(row)


def delete_channel(db: DBSession, channel_id: str) -> dict:
    row = db.get(Channel, channel_id)
    if row is None:
        raise KeyError("channel not found")
    data = _row_dict(row)
    db.delete(row)
    db.commit()
    return data


def set_status(db: DBSession, channel_id: str, status: str, error: str = "") -> None:
    row = db.get(Channel, channel_id)
    if row is None:
        return
    row.status = status
    row.last_error = (error or "")[:500]
    from datetime import datetime, timezone

    row.last_checked_at = datetime.now(timezone.utc)
    db.commit()


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #
async def provider_test(provider: str, creds: dict) -> dict:
    """Real credential validation per provider."""
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            if provider == "kapso":
                key = creds.get("api_key", "")
                if not key:
                    return {"ok": False, "error": "api_key required"}
                pid = creds.get("phone_number_id", "")
                url = (
                    f"https://api.kapso.ai/platform/v1/whatsapp/phone_numbers/{pid}"
                    if pid
                    else "https://api.kapso.ai/platform/v1/whatsapp/phone_numbers"
                )
                resp = await client.get(url, headers={"X-API-Key": key, "Accept": "application/json"})
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data") or []
                    if pid:
                        pn = items if isinstance(items, list) else [data.get("data") or data]
                        pn = pn[0] if pn and isinstance(pn[0], dict) else {}
                        return {"ok": True, "detail": f"{pn.get('display_name', '')} · {pn.get('display_phone_number', '')} — key valid"}
                    if isinstance(items, dict):
                        items = [items]
                    names = ", ".join(str(p.get("display_phone_number") or "?") for p in items[:5] if isinstance(p, dict))
                    return {"ok": True, "detail": f"Kapso key valid — {len(items)} number(s): {names}"}
                return {"ok": False, "error": f"Kapso {resp.status_code}: {resp.text[:200]}"}

            if provider == "meta":
                token, pid = creds.get("access_token", ""), creds.get("phone_number_id", "")
                if not token or not pid:
                    return {"ok": False, "error": "access_token and phone_number_id required"}
                resp = await client.get(
                    f"https://graph.facebook.com/v21.0/{pid}",
                    params={"fields": "display_phone_number,verified_name,quality_rating", "access_token": token},
                )
                if resp.status_code == 200:
                    d = resp.json()
                    return {"ok": True, "detail": f"{d.get('verified_name', '')} · {d.get('display_phone_number', '')} (quality {d.get('quality_rating', 'n/a')})"}
                return {"ok": False, "error": f"Graph API {resp.status_code}: {resp.text[:200]}"}

            if provider == "twilio":
                sid, tok = creds.get("account_sid", ""), creds.get("auth_token", "")
                if not sid or not tok:
                    return {"ok": False, "error": "account_sid and auth_token required"}
                resp = await client.get(
                    "https://api.twilio.com/2010-04-01/Accounts.json",
                    auth=(sid, tok),
                )
                if resp.status_code == 200:
                    name = (resp.json() or {}).get("friendly_name") or sid
                    return {"ok": True, "detail": f"Twilio account '{name}' reachable"}
                return {"ok": False, "error": f"Twilio {resp.status_code}: {resp.text[:200]}"}

            if provider == "generic":
                return {"ok": True, "detail": "saved (send endpoint is validated on first use)"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}
    return {"ok": False, "error": "unknown provider"}


async def provider_send(provider: str, creds: dict, phone_number: str, wa_id: str, text: str) -> str:
    """Send a text message through the provider. Returns the provider message id."""
    if provider == "kapso":
        key, pid = creds.get("api_key", ""), creds.get("phone_number_id", "")
        if not key or not pid:
            raise RuntimeError("channel missing api_key / phone_number_id")
        payload = {
            "messaging_product": "whatsapp", "recipient_type": "individual",
            "to": normalize_phone(wa_id), "type": "text",
            "text": {"body": text[:4096], "preview_url": False},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.kapso.ai/meta/whatsapp/v24.0/{pid}/messages",
                json=payload, headers={"X-API-Key": key, "Content-Type": "application/json"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Kapso send {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    if provider == "meta":
        token, pid = creds.get("access_token", ""), creds.get("phone_number_id", "")
        if not token or not pid:
            raise RuntimeError("channel missing access_token / phone_number_id")
        payload = {
            "messaging_product": "whatsapp", "recipient_type": "individual",
            "to": normalize_phone(wa_id), "type": "text",
            "text": {"body": text[:4096]},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{pid}/messages",
                json=payload, params={"access_token": token},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Meta send {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    if provider == "twilio":
        sid, tok = creds.get("account_sid", ""), creds.get("auth_token", "")
        sender = normalize_phone(creds.get("phone_number", ""))
        if not sid or not tok or not sender:
            raise RuntimeError("channel missing account_sid / auth_token / phone_number")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data={
                    "From": f"whatsapp:+{sender}",
                    "To": f"whatsapp:+{normalize_phone(wa_id)}",
                    "Body": text[:1600],
                },
                auth=(sid, tok),
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Twilio send {resp.status_code}: {resp.text[:300]}")
        return str((resp.json() or {}).get("sid") or "")

    if provider == "generic":
        url = creds.get("send_url", "")
        if not url:
            raise RuntimeError("channel missing send_url")
        headers = {"Content-Type": "application/json"}
        bearer = creds.get("send_bearer_token", "")
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json={"to": normalize_phone(wa_id), "text": text, "message": text}, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"send {resp.status_code}: {resp.text[:300]}")
        return ""

    raise RuntimeError(f"unknown provider {provider}")


async def provider_send_image(
    provider: str, creds: dict, phone_number: str, wa_id: str,
    image_url: str, caption: str = "",
) -> str:
    """Send an image message through the provider. Returns the provider message id.

    Only Cloud-API-compatible providers (kapso, meta) can send an image by
    public link. Twilio/generic raise so the caller can fall back to sending the
    link as plain text instead of losing the reference entirely.
    """
    url = (image_url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise RuntimeError("image must be a public http(s) link")
    cap = (caption or "").strip()[:1024]
    image: dict = {"link": url}
    if cap:
        image["caption"] = cap
    payload = {
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": normalize_phone(wa_id), "type": "image", "image": image,
    }

    if provider == "kapso":
        key, pid = creds.get("api_key", ""), creds.get("phone_number_id", "")
        if not key or not pid:
            raise RuntimeError("channel missing api_key / phone_number_id")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.kapso.ai/meta/whatsapp/v24.0/{pid}/messages",
                json=payload, headers={"X-API-Key": key, "Content-Type": "application/json"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Kapso send_image {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    if provider == "meta":
        token, pid = creds.get("access_token", ""), creds.get("phone_number_id", "")
        if not token or not pid:
            raise RuntimeError("channel missing access_token / phone_number_id")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{pid}/messages",
                json=payload, params={"access_token": token},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Meta send_image {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    raise RuntimeError(f"provider {provider} cannot send images")


def verify_signature(
    provider: str, creds: dict, raw: bytes, header: str | None, *, url: str = ""
) -> bool:
    """Verify provider webhook authenticity and fail closed when unconfigured."""
    if provider in {"kapso", "generic"}:
        secret = str(creds.get("webhook_secret") or creds.get("secret_header") or "")
        if not secret or not header:
            log.warning("%s webhook secret/signature not set — rejecting", provider)
            return False
        sig = header.strip().lower()
        if sig.startswith("sha256="):
            sig = sig[len("sha256="):]
        expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        # Accept only HMAC signatures here. Plain header tokens are deliberately
        # not accepted because they permit replay/forwarding of body changes.
        return hmac.compare_digest(expected, sig)
    if provider == "meta":
        secret = str(creds.get("app_secret") or "")
        if not secret or not header:
            return False
        sig = header.strip().lower()
        if sig.startswith("sha256="):
            sig = sig[len("sha256="):]
        expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    if provider == "twilio":
        secret = str(creds.get("auth_token") or "")
        if not secret or not header or not url:
            return False
        from urllib.parse import parse_qsl
        try:
            params = dict(parse_qsl(raw.decode("utf-8"), keep_blank_values=True))
        except UnicodeDecodeError:
            return False
        signed = url + "".join(f"{key}{params[key]}" for key in sorted(params))
        expected = __import__("base64").b64encode(
            hmac.new(secret.encode(), signed.encode(), hashlib.sha1).digest()
        ).decode()
        return hmac.compare_digest(expected, header.strip())
    return False


def parse_webhook(provider: str, creds: dict, payload: dict) -> list[Inbound]:
    """Extract inbound messages from any supported webhook payload shape."""
    out: list[Inbound] = []

    def parse_msg(msg: dict, conv_name: str = "", channel_tag: str = "") -> None:
        if not isinstance(msg, dict):
            return
        k = msg.get("kapso") or {}
        if isinstance(k, dict) and str(k.get("direction") or "inbound").lower() in ("outbound", "out"):
            return
        mtype = str(msg.get("type") or "text").lower()
        text = ""
        if mtype == "text" and isinstance(msg.get("text"), dict):
            text = str(msg["text"].get("body") or "")
        elif mtype == "interactive" and isinstance(msg.get("interactive"), dict):
            reply = msg["interactive"].get("button_reply") or msg["interactive"].get("list_reply") or {}
            text = str(reply.get("title") or "")
        # Generic JSON and Twilio form payloads use flat text fields.
        if not text:
            text = str(msg.get("text") or msg.get("body") or msg.get("message") or "")
        if isinstance(k, dict) and not text:
            text = str(k.get("content") or "")
        if not text:
            return
        sender = str(msg.get("from") or msg.get("sender") or msg.get("phone") or msg.get("wa_id") or "")
        if not sender:
            return
        message_id = str(
            msg.get("id") or msg.get("message_id") or msg.get("messageId")
            or msg.get("MessageSid") or ""
        )
        if not message_id:
            # Stable fallback for providers that omit IDs; it still deduplicates
            # webhook retries for the same body without using an empty ID.
            canonical = json.dumps(
                {"provider": provider, "from": sender, "text": text.strip()},
                sort_keys=True,
            ).encode()
            message_id = f"derived-{hashlib.sha256(canonical).hexdigest()[:48]}"
        out.append(Inbound(
            message_id=message_id[:80],
            wa_id=normalize_phone(sender),
            text=text.strip(),
            msg_type=mtype,
            sender_name=conv_name or str(msg.get("name") or msg.get("sender_name") or msg.get("ProfileName") or ""),
        ))

    if provider == "twilio":
        parse_msg(payload)
        return out

    if isinstance(payload.get("batch"), bool) and isinstance(payload.get("data"), list):
        for item in payload["data"]:
            if isinstance(item, dict):
                parse_msg(item.get("message") or item)
        return out

    if isinstance(payload.get("entry"), list):  # Meta-style envelope
        for entry in payload["entry"]:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                name = ""
                contacts = value.get("contacts") or []
                if contacts and isinstance(contacts[0], dict):
                    profile = contacts[0].get("profile") or {}
                    name = str(profile.get("name") or "")
                for msg in value.get("messages") or []:
                    parse_msg(msg, name)
        return out

    parse_msg(payload.get("message") or payload, str((payload.get("conversation") or {}).get("contact_name") or ""))
    return out


async def channel_send_text(
    provider: str, creds: dict, phone_number: str, wa_id: str, text: str
) -> str:
    """Send plain text through a stored channel; returns provider message id."""
    return await provider_send(provider, creds, phone_number, wa_id, text)


async def channel_send_image(
    provider: str, creds: dict, phone_number: str, wa_id: str,
    image_url: str, caption: str = "",
) -> str:
    """Send an image by public link through a stored channel.

    Returns the provider message id. Providers that cannot send images (twilio,
    generic) raise, so the caller can degrade to sending the URL as text.
    """
    return await provider_send_image(
        provider, creds, phone_number, wa_id, image_url, caption
    )


async def provider_upload_media(
    provider: str, creds: dict, path: Path, mime: str = "",
) -> str:
    """Upload image bytes to the provider and return its media id.

    Cloud-API-compatible providers (kapso, meta) accept a multipart upload at
    `/{phone_number_id}/media`; the returned id can then be sent as an image.
    This is what makes locally stored pictures deliverable: WhatsApp fetches a
    public link itself, but a media id needs no inbound network access to us.
    Twilio/generic raise so the caller falls back to a public link.
    """
    data = path.read_bytes()
    mime = mime or "application/octet-stream"

    if provider == "kapso":
        key, pid = creds.get("api_key", ""), creds.get("phone_number_id", "")
        if not key or not pid:
            raise RuntimeError("channel missing api_key / phone_number_id")
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"https://api.kapso.ai/meta/whatsapp/v24.0/{pid}/media",
                headers={"X-API-Key": key},
                data={"messaging_product": "whatsapp", "type": mime},
                files={"file": (path.name, data, mime)},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Kapso media upload {resp.status_code}: {resp.text[:300]}")
        return str((resp.json() or {}).get("id") or "")

    if provider == "meta":
        token, pid = creds.get("access_token", ""), creds.get("phone_number_id", "")
        if not token or not pid:
            raise RuntimeError("channel missing access_token / phone_number_id")
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{pid}/media",
                params={"access_token": token},
                data={"messaging_product": "whatsapp", "type": mime},
                files={"file": (path.name, data, mime)},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Meta media upload {resp.status_code}: {resp.text[:300]}")
        return str((resp.json() or {}).get("id") or "")

    raise RuntimeError(f"provider {provider} cannot upload media")


async def provider_send_image_by_id(
    provider: str, creds: dict, wa_id: str, media_id: str, caption: str = "",
) -> str:
    """Send an uploaded media id as an image message (Cloud API `image.id`)."""
    if not (media_id or "").strip():
        raise RuntimeError("media_id is required")
    cap = (caption or "").strip()[:1024]
    image: dict = {"id": media_id.strip()}
    if cap:
        image["caption"] = cap
    payload = {
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": normalize_phone(wa_id), "type": "image", "image": image,
    }

    if provider == "kapso":
        key, pid = creds.get("api_key", ""), creds.get("phone_number_id", "")
        if not key or not pid:
            raise RuntimeError("channel missing api_key / phone_number_id")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.kapso.ai/meta/whatsapp/v24.0/{pid}/messages",
                json=payload, headers={"X-API-Key": key, "Content-Type": "application/json"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Kapso send image {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    if provider == "meta":
        token, pid = creds.get("access_token", ""), creds.get("phone_number_id", "")
        if not token or not pid:
            raise RuntimeError("channel missing access_token / phone_number_id")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{pid}/messages",
                json=payload, params={"access_token": token},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Meta send image {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    raise RuntimeError(f"provider {provider} cannot send images")


async def channel_send_image_file(
    provider: str, creds: dict, phone_number: str, wa_id: str,
    path: Path, mime: str = "", caption: str = "",
) -> str:
    """Upload a local image through a stored channel and send it by media id.

    Used when the media base URL is not reachable from the internet (local dev
    server), so a link would never be fetched by WhatsApp.
    """
    media_id = await provider_upload_media(provider, creds, path, mime)
    return await provider_send_image_by_id(provider, creds, wa_id, media_id, caption)


async def channel_send_interactive(
    provider: str, creds: dict, phone_number: str, wa_id: str,
    text: str, buttons: list[tuple[str, str]],
) -> str:
    """Send native interactive reply-buttons through a stored channel.

    Only Cloud-API-compatible providers (kapso, meta) support the payload
    natively; others raise so the caller can fall back to numbered text.
    """
    if provider == "kapso":
        key, pid = creds.get("api_key", ""), creds.get("phone_number_id", "")
        if not key or not pid:
            raise RuntimeError("channel missing api_key / phone_number_id")
        clean = [(str(bid), str(t)[:24]) for bid, t in (buttons or []) if bid and t][:3]
        if not clean:
            raise ValueError("at least one button is required")
        payload = {
            "messaging_product": "whatsapp", "recipient_type": "individual",
            "to": normalize_phone(wa_id), "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text[:1024]},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title}}
                    for bid, title in clean
                ]},
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.kapso.ai/meta/whatsapp/v24.0/{pid}/messages",
                json=payload, headers={"X-API-Key": key, "Content-Type": "application/json"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Kapso send_interactive {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    if provider == "meta":
        token, pid = creds.get("access_token", ""), creds.get("phone_number_id", "")
        if not token or not pid:
            raise RuntimeError("channel missing access_token / phone_number_id")
        clean = [(str(bid), str(t)[:24]) for bid, t in (buttons or []) if bid and t][:3]
        if not clean:
            raise ValueError("at least one button is required")
        payload = {
            "messaging_product": "whatsapp", "recipient_type": "individual",
            "to": normalize_phone(wa_id), "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text[:1024]},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title}}
                    for bid, title in clean
                ]},
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{pid}/messages",
                json=payload, params={"access_token": token},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Meta send_interactive {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    raise RuntimeError(f"provider '{provider}' does not support interactive buttons")


async def channel_send_interactive_list(
    provider: str, creds: dict, phone_number: str, wa_id: str,
    text: str, button_label: str, rows: list[tuple[str, str, str]],
    header_text: str = "",
) -> str:
    """Send a native WhatsApp interactive list message through a stored channel.

    Only Cloud-API-compatible providers (kapso, meta) support the payload
    natively; others raise so the caller can fall back to numbered text.
    """
    clean = [
        (str(rid), str(t)[:24], str(d)[:72])
        for rid, t, d in (rows or []) if rid and t
    ][:10]
    if not clean:
        raise ValueError("at least one list row is required")
    interactive: dict = {
        "type": "list",
        "body": {"text": text[:1024]},
        "action": {
            "button": str(button_label or "Options")[:20],
            "sections": [{
                "title": "Options",
                "rows": [
                    {"id": rid, "title": t, **({"description": d} if d else {})}
                    for rid, t, d in clean
                ],
            }],
        },
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text[:60]}
    payload = {
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": normalize_phone(wa_id), "type": "interactive",
        "interactive": interactive,
    }

    if provider == "kapso":
        key, pid = creds.get("api_key", ""), creds.get("phone_number_id", "")
        if not key or not pid:
            raise RuntimeError("channel missing api_key / phone_number_id")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.kapso.ai/meta/whatsapp/v24.0/{pid}/messages",
                json=payload, headers={"X-API-Key": key, "Content-Type": "application/json"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Kapso send_interactive_list {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    if provider == "meta":
        token, pid = creds.get("access_token", ""), creds.get("phone_number_id", "")
        if not token or not pid:
            raise RuntimeError("channel missing access_token / phone_number_id")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{pid}/messages",
                json=payload, params={"access_token": token},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Meta send_interactive_list {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    raise RuntimeError(f"provider '{provider}' does not support interactive lists")


async def channel_send_carousel(
    provider: str, creds: dict, phone_number: str, wa_id: str,
    text: str, cards: list[dict],
) -> str:
    """Send a free-form swipeable carousel through a stored channel.

    `cards` must already carry a Cloud-API `header` (media id or public link),
    `body_text` and quick-reply `buttons` — see app.media.prepare_carousel_cards.
    """
    from app.kapso import build_interactive_carousel_payload

    payload = build_interactive_carousel_payload(wa_id, text, cards)

    if provider == "kapso":
        key, pid = creds.get("api_key", ""), creds.get("phone_number_id", "")
        if not key or not pid:
            raise RuntimeError("channel missing api_key / phone_number_id")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://api.kapso.ai/meta/whatsapp/v24.0/{pid}/messages",
                json=payload, headers={"X-API-Key": key, "Content-Type": "application/json"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Kapso send carousel {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    if provider == "meta":
        token, pid = creds.get("access_token", ""), creds.get("phone_number_id", "")
        if not token or not pid:
            raise RuntimeError("channel missing access_token / phone_number_id")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{pid}/messages",
                json=payload, params={"access_token": token},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Meta send carousel {resp.status_code}: {resp.text[:300]}")
        try:
            return str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    raise RuntimeError(f"provider '{provider}' does not support carousels")


# --------------------------------------------------------------------------- #
# primary-channel routing (agent send path)
# --------------------------------------------------------------------------- #
async def send_via_primary(db: DBSession, wa_id: str, text: str) -> tuple[str, str]:
    """Send through the primary enabled channel if one exists.

    Returns (status, error_or_message_id). Falls back to the env Kapso
    transport when no channel is configured — so the existing setup keeps
    working untouched.
    """
    row = db.execute(
        select(Channel).where(Channel.is_primary == 1, Channel.enabled == 1)
    ).scalars().first()
    if row is None:
        return ("fallback", "")
    creds = decrypt_json(row.credentials_enc)
    try:
        msg_id = await provider_send(row.provider, creds, row.phone_number, wa_id, text)
        return ("sent", msg_id)
    except Exception as exc:  # noqa: BLE001
        set_status(db, row.id, "error", str(exc))
        return ("error", str(exc))
