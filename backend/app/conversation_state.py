"""Persisted booking-flow state for the WhatsApp conversation.

The AI model must not be trusted to remember which step the customer is on.
This module keeps a tiny, explicit state per conversation in the existing
``settings`` key/value table, so a tap can always be matched against the step
that produced it — even after a backend restart.

Only the *flow* lives here (chosen car, package, schedule, handover, KYC).
Prices, availability and bookings stay in the fleet/booking tables, which
remain the single source of truth.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.database import Setting

_PREFIX = "flow:"
_WELCOME_PREFIX = "welcome:"
# A stale flow must never hijack a later conversation. Six hours is long enough
# for a normal WhatsApp chat and short enough to expire overnight.
_TTL = timedelta(hours=6)

# Rental flow stages are owned by app/rental_flow.py (WELCOME, MENU, BROWSE,
# DURATION, DRIVE, PICK_DATE, PICK_TIME, HANDOVER, ADDRESS, KYC, SUMMARY).


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _key(conversation_id: str) -> str:
    return (_PREFIX + (conversation_id or "").strip())[:64]


def get_state(db: DBSession, conversation_id: str) -> dict[str, Any]:
    """Return ``{"state": ..., "data": {...}, "updated": ...}`` (never raises).

    A missing, malformed or expired row is treated as a brand-new flow instead
    of breaking the turn.
    """
    if not conversation_id:
        return {}
    row = db.get(Setting, _key(conversation_id))
    if row is None or not row.value:
        return {}
    try:
        payload = json.loads(row.value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    updated = _aware(payload.get("updated"))
    if updated is None or _now() - updated > _TTL:
        return {}
    return payload


def set_state(
    db: DBSession, conversation_id: str, state: str, **data: Any,
) -> dict[str, Any]:
    """Persist the current menu step plus the context the next tap needs."""
    if not conversation_id:
        return {}
    payload = {
        "state": (state or "").strip()[:40],
        "data": {k: v for k, v in data.items() if v not in (None, "")},
        "updated": _now().isoformat(),
    }
    key = _key(conversation_id)
    row = db.get(Setting, key)
    text = json.dumps(payload, ensure_ascii=False)[:4000]
    if row is None:
        db.add(Setting(key=key, value=text))
    else:
        row.value = text
    db.flush()
    return payload


def clear_state(db: DBSession, conversation_id: str) -> None:
    if not conversation_id:
        return
    row = db.get(Setting, _key(conversation_id))
    if row is not None:
        db.delete(row)
        db.flush()


def _welcome_key(conversation_id: str) -> str:
    return (_WELCOME_PREFIX + (conversation_id or "").strip())[:64]


def has_been_welcomed(db: DBSession, conversation_id: str) -> bool:
    """True once this conversation has received the first-contact welcome.

    Kept separate from the short-lived flow state: ``clear_state`` runs on
    every completed action, so a flag stored there would make the agent greet
    the customer again in the middle of a chat. This marker never expires and
    is never cleared by a flow transition.
    """
    if not conversation_id:
        return False
    return db.get(Setting, _welcome_key(conversation_id)) is not None


def mark_welcomed(db: DBSession, conversation_id: str) -> None:
    if not conversation_id:
        return
    key = _welcome_key(conversation_id)
    if db.get(Setting, key) is None:
        db.add(Setting(key=key, value="1"))
        db.flush()
