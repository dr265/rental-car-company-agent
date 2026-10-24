"""Kapso WhatsApp transport (https://docs.kapso.ai).

Kapso exposes a WhatsApp Cloud-API-compatible surface:

  POST https://api.kapso.ai/meta/whatsapp/v24.0/{phone_number_id}/messages
       headers: X-API-Key (project API key) — no Bearer token
  Inbound events arrive as webhooks signed with
       X-Webhook-Signature: hmac-sha256-hex-of-raw-body (secret = KAPSO_WEBHOOK_SECRET)
  Batched deliveries use the envelope {type, batch: true, data: [...]}.

This is the transport used in production; it is kept verbatim across
deployments so the existing credentials, webhook registration and message
shapes keep working — no new WhatsApp setup is required.

Credentials are read ONLY from environment via app.config — never hardcoded.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import KAPSO_API_KEY, KAPSO_PHONE_NUMBER_ID, KAPSO_WEBHOOK_SECRET

log = logging.getLogger("rental.kapso")

API_BASE = "https://api.kapso.ai"
META_API = f"{API_BASE}/meta/whatsapp/v24.0"
PLATFORM_API = f"{API_BASE}/platform/v1"


def normalize_phone(raw: str | None) -> str:
    """E.164-ish canonical form: digits only (leading '+' dropped).

    WhatsApp addresses customers by digits-only wa_id; storing that form keeps
    lookups stable regardless of how a number was written in a message.
    """
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    return digits


def display_phone(normalized: str) -> str:
    return f"+{normalized}" if normalized else ""


@dataclass
class InboundMessage:
    """Normalized inbound WhatsApp message (already direction-filtered)."""

    message_id: str
    wa_id: str  # customer phone, digits only
    text: str
    msg_type: str = "text"
    sender_name: str = ""
    conversation_id: str = ""
    channel_id: str = ""
    raw_type: str = "text"
    # id of a tapped WhatsApp reply-button (interactive messages), e.g. 'lang_en'
    button_id: str = ""
    media: dict[str, Any] = field(default_factory=dict)

    @property
    def display_number(self) -> str:
        return display_phone(self.wa_id)


class KapsoError(RuntimeError):
    """Raised when the Kapso API rejects an operation (includes status + body)."""

    def __init__(self, status: int, body: str, op: str = "request") -> None:
        self.status = status
        self.body = body[:500]
        super().__init__(f"Kapso {op} failed HTTP {status}: {self.body}")

    @property
    def is_auth(self) -> bool:
        return self.status in (401, 403)

    @property
    def is_rate_limit(self) -> bool:
        return self.status == 429


# --------------------------------------------------------------------------- #
# actionable send-failure explanations
# --------------------------------------------------------------------------- #
# WhatsApp/Meta reject outbound messages for a handful of very specific
# reasons, and several of them look identical from the outside ("the agent
# replies to me but nobody else"). Naming the real cause is the difference
# between a mysterious bug and a five-minute fix, so the recognised codes are
# translated here — next to the transport — and stored on the outbound message
# row / shown in the owner console.
_META_SEND_HINTS: dict[int, str] = {
    131030: (
        "RECIPIENT NOT ALLOWED — this WhatsApp number is running in test/sandbox "
        "mode, so it can only message numbers on its allowlist. Add the "
        "customer's number under Meta App Dashboard → WhatsApp → API Setup → the "
        "allowed 'To' recipient list, or move the number to Live mode"
    ),
    131047: (
        "24-HOUR WINDOW CLOSED — WhatsApp only permits free-form replies within "
        "24 hours of the customer's last message. Wait for the customer to "
        "message first, or send an approved template"
    ),
    131026: (
        "MESSAGE UNDELIVERABLE — this recipient cannot receive WhatsApp messages "
        "(not on WhatsApp, or messaging blocked for them)"
    ),
    131051: "UNSUPPORTED MESSAGE TYPE for this recipient",
    132000: "TEMPLATE MISMATCH — the payload does not match an approved template",
    132001: "TEMPLATE NOT FOUND or not approved for this number",
    133010: "PHONE NUMBER NOT REGISTERED with the WhatsApp Business Platform",
    131000: "PROVIDER-SIDE UNKNOWN ERROR — retry; if it persists, check the number status",
    368: "NUMBER TEMPORARILY BLOCKED for policy violations",
    80007: "RATE LIMIT reached for this phone number — slow the sends down",
}

_CODE_PATTERNS = (
    re.compile(r'"code"\s*:\s*(\d{3,6})'),
    re.compile(r'error[ _]?code["\s:=]+(\d{3,6})', re.IGNORECASE),
    re.compile(r"#(\d{3,6})"),
    re.compile(r"\b(131\d{3}|132\d{3}|133\d{3}|80007|368)\b"),
)


def _error_code(text: str) -> int:
    for pattern in _CODE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                continue
    return 0


def describe_send_error(payload: Any) -> str:
    """Turn a failed send into something the owner can act on.

    Accepts an exception, a KapsoError or a raw provider body and returns the
    original detail with a concrete next step appended when the failure is a
    recognised WhatsApp/Meta code. Never returns a credential.
    """
    text = str(payload or "").strip()
    if not text:
        return "send failed with no detail returned by the provider"
    hint = _META_SEND_HINTS.get(_error_code(text), "")
    detail = text[:220]
    if hint:
        return f"{hint} — provider said: {detail}"
    return text[:300]


CAROUSEL_MAX_CARDS = 10
CAROUSEL_CARD_BODY_CHARS = 160
CAROUSEL_BUTTON_LABEL_CHARS = 20


def build_interactive_carousel_payload(
    to_wa_id: str, body_text: str, cards: list[dict[str, Any]],
) -> dict[str, Any]:
    """Cloud-API payload for a free-form swipeable carousel.

    Each prepared card is `{header: {type:image, image:{id|link}}, body_text,
    buttons: [(id, title)]}`. WhatsApp caps carousels at 10 cards, each card
    body at 160 characters (two line breaks) and every card must use the same
    button structure — all enforced here.
    """
    wa = normalize_phone(to_wa_id)
    if not wa:
        raise ValueError("destination phone number is empty")
    usable = [card for card in (cards or []) if card.get("header")]
    if len(usable) < 2:
        raise ValueError("a carousel needs at least two cards with images")
    usable = usable[:CAROUSEL_MAX_CARDS]
    button_count = min(
        (len(card.get("buttons") or []) for card in usable), default=0
    )
    if button_count < 1:
        raise ValueError("every carousel card needs at least one button")

    payload_cards: list[dict[str, Any]] = []
    for index, card in enumerate(usable):
        item: dict[str, Any] = {
            # Meta's carousel schema is snake_case; camelCase is rejected by
            # the Kapso proxy with HTTP 422 "Invalid message payload".
            "card_index": index,
            "type": "cta_url",
            "header": card["header"],
            "action": {
                "buttons": [
                    {
                        "type": "quick_reply",
                        "quick_reply": {
                            "id": str(bid)[:256],
                            "title": str(title)[:CAROUSEL_BUTTON_LABEL_CHARS],
                        },
                    }
                    for bid, title in (card.get("buttons") or [])[:button_count]
                ]
            },
        }
        body = str(card.get("body_text") or "").strip()
        if body:
            item["body"] = {"text": body[:CAROUSEL_CARD_BODY_CHARS]}
        payload_cards.append(item)

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa,
        "type": "interactive",
        "interactive": {
            "type": "carousel",
            "body": {"text": (body_text or "").strip()[:1024] or "Browse our cars"},
            "action": {"cards": payload_cards},
        },
    }


class KapsoClient:
    """Thin async client over the Kapso WhatsApp API (Cloud API compatible)."""

    def __init__(
        self,
        api_key: str = KAPSO_API_KEY,
        phone_number_id: str = KAPSO_PHONE_NUMBER_ID,
        webhook_secret: str = KAPSO_WEBHOOK_SECRET,
    ) -> None:
        self.api_key = api_key
        self.phone_number_id = phone_number_id
        self.webhook_secret = webhook_secret

    # ------------------------------------------------------------------ #
    # state
    # ------------------------------------------------------------------ #
    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.phone_number_id)

    def status_snapshot(self) -> dict[str, Any]:
        """Credentials state WITHOUT ever exposing the secrets themselves."""
        return {
            "api_key_set": bool(self.api_key),
            "phone_number_id_set": bool(self.phone_number_id),
            "webhook_secret_set": bool(self.webhook_secret),
            "phone_number_id_tail": f"…{self.phone_number_id[-4:]}" if self.phone_number_id else "",
        }

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #
    def _headers(self, api: bool = True) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if api and self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    async def _request(self, method: str, url: str, *, json_body: dict | None = None, op: str = "request") -> dict[str, Any]:
        if not self.api_key:
            raise KapsoError(401, "KAPSO_API_KEY is not configured", op)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                resp = await client.request(method, url, json=json_body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise KapsoError(0, f"network error: {exc}", op) from exc
        if resp.status_code >= 400:
            raise KapsoError(resp.status_code, resp.text, op)
        try:
            return resp.json()
        except ValueError:
            return {}

    # ------------------------------------------------------------------ #
    # connection diagnostics (Connection page)
    # ------------------------------------------------------------------ #
    async def verify_credentials(self) -> dict[str, Any]:
        """Real credential check against the Kapso platform API.

        Returns {ok, detail, phone_number:{...}} — no exception on API-level
        failure, so the UI can show the true reason.
        """
        if not self.api_key:
            return {"ok": False, "error": "KAPSO_API_KEY not set in backend/.env"}
        if not self.phone_number_id:
            return {"ok": False, "error": "KAPSO_PHONE_NUMBER_ID not set in backend/.env"}
        try:
            data = await self._request(
                "GET",
                f"{PLATFORM_API}/whatsapp/phone_numbers/{self.phone_number_id}",
                op="verify",
            )
        except KapsoError as exc:
            hint = {
                401: "API key rejected by Kapso (invalid or revoked)",
                403: "API key lacks access to this phone number",
                404: "Phone number ID not found in this Kapso project",
            }.get(exc.status, "")
            return {"ok": False, "error": f"{exc}{(' — ' + hint) if hint else ''}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"unexpected error: {exc}"}

        pn = data.get("data") or data or {}
        info = {
            "id": str(pn.get("id") or self.phone_number_id),
            "display_phone_number": str(pn.get("display_phone_number") or pn.get("phone_number") or ""),
            "verified_name": str(pn.get("verified_name") or pn.get("display_name") or ""),
            "quality_rating": str(pn.get("quality_rating") or ""),
            "platform": str(pn.get("platform") or ""),
            "status": str(pn.get("status") or ""),
        }
        detail = f"{info['verified_name'] or 'WhatsApp number'} · {info['display_phone_number']}"
        if info["quality_rating"]:
            detail += f" · quality {info['quality_rating']}"
        return {"ok": True, "detail": detail, "phone_number": info}

    # ------------------------------------------------------------------ #
    # outbound messaging
    # ------------------------------------------------------------------ #
    async def send_text(self, to_wa_id: str, text: str) -> dict[str, Any]:
        """Send a plain text message. Returns {message_id} from Kapso."""
        wa = normalize_phone(to_wa_id)
        if not wa:
            raise ValueError("destination phone number is empty")
        if not text.strip():
            raise ValueError("refusing to send an empty WhatsApp message")
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa,
            "type": "text",
            "text": {"body": text[:4096], "preview_url": False},
        }
        data = await self._request(
            "POST",
            f"{META_API}/{self.phone_number_id}/messages",
            json_body=payload,
            op="send",
        )
        return {"message_id": self._message_id(data)}

    @staticmethod
    def _message_id(data: dict[str, Any]) -> str:
        try:
            return str((data.get("messages") or [{}])[0].get("id") or "")
        except Exception:  # noqa: BLE001
            return ""

    async def send_image(
        self, to_wa_id: str, image_url: str, caption: str = "",
    ) -> dict[str, Any]:
        """Send an image message by public link (Cloud API `type: image`).

        Kapso/Meta fetch the bytes themselves, so the URL must be publicly
        reachable over http(s) and serve raw image bytes — a local file path or
        a `file://` link is rejected by the API, so callers must host the file
        first. A caption rides along on the same message (max 1024 chars).
        """
        wa = normalize_phone(to_wa_id)
        if not wa:
            raise ValueError("destination phone number is empty")
        url = (image_url or "").strip()
        if not url:
            raise ValueError("image_url is required")
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("image_url must be a public http(s) link")
        image: dict[str, Any] = {"link": url}
        cap = (caption or "").strip()[:1024]
        if cap:
            image["caption"] = cap
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa,
            "type": "image",
            "image": image,
        }
        data = await self._request(
            "POST",
            f"{META_API}/{self.phone_number_id}/messages",
            json_body=payload,
            op="send_image",
        )
        return {"message_id": self._message_id(data)}

    async def upload_media(self, path: "Path", mime: str = "") -> str:
        """Upload image bytes to the Cloud API and return the media id.

        Sending a picture by media id needs no inbound network access to us, so
        this is the path that works for images stored inside the project while
        PUBLIC_BASE_URL is still a localhost dev address.
        """
        from pathlib import Path as _Path

        if not self.api_key or not self.phone_number_id:
            raise RuntimeError("Kapso credentials missing in backend/.env")
        file_path = _Path(path)
        data = file_path.read_bytes()
        content_type = mime or "application/octet-stream"
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{META_API}/{self.phone_number_id}/media",
                # NOTE: no Content-Type header here — httpx sets the
                # multipart/form-data boundary itself when files= is used.
                # Sending application/json (as _headers() does) makes Kapso
                # reject the upload with 400 Bad Request and no image is ever
                # delivered (no Content-Type on multipart uploads).
                headers={"X-API-Key": self.api_key},
                data={"messaging_product": "whatsapp", "type": content_type},
                files={"file": (file_path.name, data, content_type)},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Kapso media upload {resp.status_code}: {resp.text[:300]}")
        media_id = str((resp.json() or {}).get("id") or "")
        if not media_id:
            raise RuntimeError("Kapso media upload returned no media id")
        return media_id

    async def send_image_by_id(
        self, to_wa_id: str, media_id: str, caption: str = "",
    ) -> dict[str, Any]:
        """Send an uploaded media id as an image message (`image.id`)."""
        wa = normalize_phone(to_wa_id)
        if not wa:
            raise ValueError("destination phone number is empty")
        if not (media_id or "").strip():
            raise ValueError("media_id is required")
        image: dict[str, Any] = {"id": media_id.strip()}
        cap = (caption or "").strip()[:1024]
        if cap:
            image["caption"] = cap
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa,
            "type": "image",
            "image": image,
        }
        data = await self._request(
            "POST",
            f"{META_API}/{self.phone_number_id}/messages",
            json_body=payload,
            op="send_image",
        )
        return {"message_id": self._message_id(data)}

    async def send_interactive_buttons(
        self, to_wa_id: str, body_text: str, buttons: list[tuple[str, str]]
    ) -> dict[str, Any]:
        """Send native WhatsApp interactive reply-buttons (Cloud API payload).

        `buttons` is a list of (button_id, label); labels are hard-capped at 24
        chars by WhatsApp and at most 3 buttons are allowed — both enforced
        here so the API never rejects the shape.
        """
        wa = normalize_phone(to_wa_id)
        if not wa:
            raise ValueError("destination phone number is empty")
        clean = [(str(bid), str(t)[:24]) for bid, t in (buttons or []) if bid and t][:3]
        if not clean:
            raise ValueError("at least one button is required")
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text[:1024]},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": bid, "title": title}}
                        for bid, title in clean
                    ]
                },
            },
        }
        data = await self._request(
            "POST",
            f"{META_API}/{self.phone_number_id}/messages",
            json_body=payload,
            op="send_interactive",
        )
        return {"message_id": self._message_id(data)}

    async def send_interactive_list(
        self, to_wa_id: str, body_text: str, button_label: str,
        rows: list[tuple[str, str, str]], header_text: str = "",
    ) -> dict[str, Any]:
        """Send a native WhatsApp interactive list message (Cloud API shape).

        `rows` is a list of (row_id, title, description); WhatsApp caps lists
        at 10 rows with 24-char titles and a 20-char button label — all
        enforced here so the API never rejects the shape.
        """
        wa = normalize_phone(to_wa_id)
        if not wa:
            raise ValueError("destination phone number is empty")
        clean = [
            (str(rid), str(t)[:24], str(d)[:72])
            for rid, t, d in (rows or []) if rid and t
        ][:10]
        if not clean:
            raise ValueError("at least one list row is required")
        interactive: dict[str, Any] = {
            "type": "list",
            "body": {"text": body_text[:1024]},
            "action": {
                "button": str(button_label or "Options")[:20],
                "sections": [{
                    "title": "Options",
                    "rows": [
                        {"id": rid, "title": t, **( {"description": d} if d else {})}
                        for rid, t, d in clean
                    ],
                }],
            },
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text[:60]}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa,
            "type": "interactive",
            "interactive": interactive,
        }
        data = await self._request(
            "POST",
            f"{META_API}/{self.phone_number_id}/messages",
            json_body=payload,
            op="send_interactive_list",
        )
        return {"message_id": self._message_id(data)}

    async def send_interactive_carousel(
        self, to_wa_id: str, body_text: str, cards: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Send a free-form swipeable carousel (inside the 24-hour window)."""
        payload = build_interactive_carousel_payload(to_wa_id, body_text, cards)
        data = await self._request(
            "POST",
            f"{META_API}/{self.phone_number_id}/messages",
            json_body=payload,
            op="send_interactive_carousel",
        )
        return {"message_id": self._message_id(data)}

    async def mark_read(self, wa_message_id: str) -> None:
        """Blue ticks: mark an inbound message as read (best effort)."""
        if not wa_message_id:
            return
        try:
            await self._request(
                "POST",
                f"{META_API}/{self.phone_number_id}/messages",
                json_body={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": wa_message_id,
                },
                op="mark_read",
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("mark_read failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------ #
    # webhook security + parsing
    # ------------------------------------------------------------------ #
    def verify_signature(self, raw_body: bytes, signature_header: str | None) -> bool:
        """HMAC-SHA256 over the exact bytes Kapso signed.

        Accepts both bare hex and 'sha256=<hex>' forms. With no webhook secret
        configured we fail CLOSED for security (log loudly — configure it).
        """
        if not self.webhook_secret:
            log.warning("KAPSO_WEBHOOK_SECRET not set — rejecting webhook (fail closed)")
            return False
        if not signature_header:
            return False
        sig = signature_header.strip().lower()
        if sig.startswith("sha256="):
            sig = sig[len("sha256="):]
        computed = hmac.new(self.webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        try:
            return hmac.compare_digest(computed, sig)
        except Exception:  # noqa: BLE001
            return False

    def parse_webhook(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Extract every inbound customer message from a Kapso webhook payload.

        Handles the single form, Meta-style {entry:[{changes:[...]}]} form, and
        the buffered batch envelope {batch:true, data:[...]}. Outbound echoes
        (kapso.direction == 'outbound') are ignored.
        """
        events: list[dict[str, Any]] = []
        if payload.get("batch") and isinstance(payload.get("data"), list):
            events = [e for e in payload["data"] if isinstance(e, dict)]
        elif isinstance(payload.get("entry"), list):
            for entry in payload["entry"]:
                if not isinstance(entry, dict):
                    continue
                for change in entry.get("changes") or []:
                    value = change.get("value") or {}
                    if not isinstance(value, dict):
                        continue
                    contacts = value.get("contacts") or []
                    profile = contacts[0].get("profile") if contacts and isinstance(contacts[0], dict) else {}
                    contact_name = str((profile or {}).get("name") or "")
                    for message in value.get("messages") or []:
                        if isinstance(message, dict):
                            events.append({
                                "message": message,
                                "conversation": {"contact_name": contact_name},
                            })
        else:
            events = [payload]

        parsed: list[InboundMessage] = []
        for ev in events:
            msg = self._parse_single(ev)
            if msg is not None:
                parsed.append(msg)
        return parsed

    def parse_statuses(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        """Extract delivery-status events ({id, status}) from a webhook payload.

        Meta-style envelopes carry them in value.statuses; some Kapso
        deliveries send a flat {statuses: [...]} or a single status object.
        Unknown shapes simply yield nothing (never an error).
        """
        out: list[dict[str, str]] = []

        def _collect(value: Any) -> None:
            if not isinstance(value, dict):
                return
            for st in value.get("statuses") or []:
                if not isinstance(st, dict):
                    continue
                mid = str(st.get("id") or st.get("message_id") or "")
                status = str(st.get("status") or "").lower()
                if mid and status:
                    out.append({"message_id": mid, "status": status})

        if isinstance(payload.get("entry"), list):
            for entry in payload["entry"]:
                if not isinstance(entry, dict):
                    continue
                for change in entry.get("changes") or []:
                    _collect((change or {}).get("value") or {})
        if payload.get("batch") and isinstance(payload.get("data"), list):
            for item in payload["data"]:
                if isinstance(item, dict):
                    _collect(item)
        _collect(payload)
        return out

    def _parse_single(self, payload: dict[str, Any]) -> InboundMessage | None:
        msg = payload.get("message") or {}
        if not isinstance(msg, dict):
            msg = {}
        kapso = msg.get("kapso") or {}
        if isinstance(kapso, dict):
            direction = str(kapso.get("direction") or "inbound").lower()
            if direction in ("outbound", "out"):
                return None  # echo of our own send
        mtype = str(msg.get("type") or "text").lower()

        text = ""
        button_id = ""
        media: dict[str, Any] = {}
        if mtype == "text" and isinstance(msg.get("text"), dict):
            text = str(msg["text"].get("body") or "")
        elif mtype == "interactive" and isinstance(msg.get("interactive"), dict):
            inter = msg["interactive"]
            reply = inter.get("button_reply") or inter.get("list_reply") or {}
            text = str(reply.get("title") or "")
            button_id = str(reply.get("id") or "")
            mtype = "interactive"
        elif isinstance(msg.get("button"), dict):
            text = str(msg["button"].get("text") or "")
            button_id = str(msg["button"].get("id") or "")
            mtype = "interactive"
        elif mtype in ("image", "video", "audio", "document", "sticker"):
            section = msg.get(mtype)
            if isinstance(section, dict):
                media = {
                    "id": str(section.get("id") or ""),
                    "mime_type": str(section.get("mime_type") or ""),
                    "caption": str(section.get("caption") or ""),
                    "filename": str(section.get("filename") or ""),
                }
                text = media["caption"]
        if isinstance(kapso.get("content"), str) and not text:
            text = kapso["content"]
        if not text and not media:
            return None  # nothing actionable (status events etc.)

        sender = str(msg.get("from") or (payload.get("conversation") or {}).get("phone_number") or "")
        wa = normalize_phone(sender)
        if not wa:
            return None

        conversation = payload.get("conversation") or {}
        message_id = str(msg.get("id") or "")
        if not message_id:
            return None

        sender_name = ""
        conv = conversation if isinstance(conversation, dict) else {}
        sender_name = str(conv.get("contact_name") or "")
        profile = msg.get("profile")
        if not sender_name and isinstance(profile, dict):
            sender_name = str(profile.get("name") or "")

        return InboundMessage(
            message_id=message_id,
            wa_id=wa,
            text=text.strip(),
            msg_type="text" if text and not media else mtype,
            sender_name=sender_name,
            conversation_id=str(conv.get("id") or ""),
            raw_type=mtype,
            button_id=button_id,
            media=media,
        )


# Shared client instance (credentials immutable at runtime).
kapso = KapsoClient()
