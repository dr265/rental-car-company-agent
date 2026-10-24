"""Persistent customer memory: regex fact extraction + per-customer fact store.

Only facts stated by the customer (or captured by the LLM's remember[] output)
are stored — nothing invented. Facts survive restarts in the customers'
customer_memories table and are injected into every prompt as verified memory.

Rental keys: name, budget, pickup_location, vehicle_pref, trip_type, passengers,
license, trip_dates, drive_mode, duration, delivery_address, payment_pref,
instruction, other (+ language, managed by app/languages.py).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.database import CustomerMemory, Message

# --------------------------------------------------------------------------- #
# deterministic extraction (runs on every inbound message, no LLM needed)
# --------------------------------------------------------------------------- #
NAME_RE = re.compile(
    r"(?:\bmy name is\b|\bi am\b|\bi'm\b|\bthis is\b|\bmera naam\b|\bmain\b)\s+"
    r"(?-i:([A-Z][a-z]{1,15}(?:\s+[A-Z][a-z]{1,15})?))",
    re.IGNORECASE,
)
BUDGET_RE = re.compile(
    r"\b(budget|till|upto|up to|under|below|around|within|approx|max)\s*(?:is\s*)?"
    r"(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)(?:\s*(k|lakh|lac|lakhs|cr|crore))?",
    re.IGNORECASE,
)
TRIP_TYPE_RE = re.compile(
    r"\b(airport|railway|station|wedding|shaadi|business trip|outstation|"
    r"hill station|weekend trip|family trip|road trip|city use|office|"
    r"self drive|chauffeur)\b",
    re.IGNORECASE,
)
VEHICLE_RE = re.compile(
    r"\b(thar roxx|thar 4x4|thar|scorpio n|scorpio s11|scorpio|xuv ?700|xuv|"
    r"endeavour|endeavor|fortuner|ertiga|fronx|dzire|baleno|swift|aura|"
    r"brezza|creta|verna|venue|suv|sedan|hatchback|muv|7 seater)\b",
    re.IGNORECASE,
)
DRIVE_MODE_RE = re.compile(
    r"\b(self[ -]?drive|without driver|chauffeur|with driver|driver\b|"
    r"chauffeur[- ]driven)\b",
    re.IGNORECASE,
)
DURATION_RE = re.compile(
    r"\b(6|12|24)\s*(?:hours?|hrs?|h)\b|\b(6|12|24)\s*hour package\b",
    re.IGNORECASE,
)
PASSENGERS_RE = re.compile(
    r"\b(\d{1,2})\s*(?:people|persons?|passengers?|pax|seater|seats?)\b",
    re.IGNORECASE,
)
PICKUP_RE = re.compile(
    r"\b(?:pick\s*-?\s*up|pickup|collect)\s+(?:from|at)\s+([A-Za-z0-9][A-Za-z0-9 ,.\-/()#]{2,120})",
    re.IGNORECASE,
)
LICENSE_RE = re.compile(
    r"\b(driving licen[cs]e|dl\b|licen[cs]e|aadhaar|voter id)\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(\d{1,2}[-/ ](?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|today|tomorrow|day after tomorrow|aaj|kal|parso|"
    r"this (?:weekend|saturday|sunday|monday|tuesday|wednesday|thursday|friday)|"
    r"next (?:week|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    re.IGNORECASE,
)
HANDOVER_RE = re.compile(
    r"\b(doorstep|home delivery|deliver(?:y)? to|hub pickup|self pickup|"
    r"pick up from hub|office pickup)\b",
    re.IGNORECASE,
)
PAYMENT_RE = re.compile(
    r"\b(cash|upi|online payment|card|pay at pickup|pay on delivery)\b",
    re.IGNORECASE,
)

# Keys whose values ACCUMULATE across messages instead of being replaced.
ACCUMULATE_KEYS = {"vehicle_pref", "trip_type"}
ACCUMULATE_MAX_VALUES = 8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_budget(raw: str, unit: str | None) -> str:
    value = raw.replace(",", "")
    try:
        num = float(value)
    except ValueError:
        return f"{raw}{unit or ''}"
    unit = (unit or "").lower()
    if unit.startswith("k"):
        num *= 1_000
    elif unit.startswith("l"):
        num *= 100_000
    elif unit.startswith("cr"):
        num *= 10_000_000
    return f"₹{int(num)}"


def extract_facts(db: DBSession, customer_id: str, text: str) -> list[str]:
    """Store durable rental facts stated in a customer message."""
    stored: list[str] = []
    text = (text or "").strip()
    if not text:
        return stored

    m = NAME_RE.search(text)
    if m:
        name = m.group(1).strip().title()
        if name and name.lower() not in ("hi", "hello", "hey", "looking", "interested"):
            _upsert(db, customer_id, "name", name, evidence=text[:100])
            stored.append("name")

    for m in BUDGET_RE.finditer(text):
        amount = _normalize_budget(m.group(2), m.group(3))
        _upsert(db, customer_id, "budget", amount, evidence=text[:100])
        stored.append("budget")
        break

    m = PICKUP_RE.search(text)
    if m:
        pickup = " ".join(m.group(1).split()).strip(" ,.")
        if len(pickup) >= 3:
            _upsert(db, customer_id, "pickup_location", pickup[:200], evidence=text[:100])
            stored.append("pickup_location")

    vehicles = {m.group(0).strip().lower() for m in VEHICLE_RE.finditer(text)}
    if vehicles:
        _upsert(db, customer_id, "vehicle_pref", "/".join(sorted(vehicles)),
                evidence=text[:100])
        stored.append("vehicle_pref")

    trips = {m.group(0).strip().lower() for m in TRIP_TYPE_RE.finditer(text)}
    if trips:
        _upsert(db, customer_id, "trip_type", "/".join(sorted(trips)),
                evidence=text[:100])
        stored.append("trip_type")

    m = DURATION_RE.search(text)
    if m:
        _upsert(db, customer_id, "duration", f"{(m.group(1) or m.group(2))} hours",
                evidence=text[:100])
        stored.append("duration")

    m = DRIVE_MODE_RE.search(text)
    if m:
        raw = m.group(0).lower()
        value = "chauffeur" if ("chauffeur" in raw or "with driver" in raw) else "self"
        _upsert(db, customer_id, "drive_mode", value, evidence=text[:100])
        stored.append("drive_mode")

    m = PASSENGERS_RE.search(text)
    if m:
        _upsert(db, customer_id, "passengers", m.group(1), evidence=text[:100])
        stored.append("passengers")

    m = DATE_RE.search(text)
    if m:
        _upsert(db, customer_id, "trip_dates", m.group(0).lower(), evidence=text[:100])
        stored.append("trip_dates")

    m = LICENSE_RE.search(text)
    if m:
        _upsert(db, customer_id, "license", "available", evidence=text[:100])
        stored.append("license")

    m = HANDOVER_RE.search(text)
    if m:
        raw = m.group(0).lower()
        value = "doorstep" if ("door" in raw or "home" in raw or "deliver" in raw) else "hub"
        _upsert(db, customer_id, "delivery_address", value, evidence=text[:100])
        stored.append("delivery_address")

    m = PAYMENT_RE.search(text)
    if m:
        _upsert(db, customer_id, "payment_pref", m.group(0).lower(), evidence=text[:100])
        stored.append("payment_pref")

    if re.search(r"\b(?:please|kindly|note|instruction|likhte|likhna|likh do)\b", text, re.I):
        _upsert(db, customer_id, "instruction", text[:250], evidence=text[:100])
        stored.append("instruction")

    return stored


def _upsert(db: DBSession, customer_id: str, key: str, value: str, evidence: str = "") -> None:
    row = db.execute(
        select(CustomerMemory).where(
            CustomerMemory.customer_id == customer_id, CustomerMemory.key == key
        )
    ).scalars().first()
    if row is not None and key in ACCUMULATE_KEYS and value[:300] != row.value:
        previous = [v.strip() for v in row.value.split("/") if v.strip()]
        candidate = value.strip()
        for part in candidate.split("/"):
            part = part.strip()
            if part and part.lower() not in {p.lower() for p in previous}:
                previous.append(part)
        merged = "/".join(previous[-ACCUMULATE_MAX_VALUES:])
        if merged != row.value:
            row.value = merged[:300]
            row.source = evidence[:120]
            row.updated_at = _now()
    elif row is None:
        db.add(CustomerMemory(
            customer_id=customer_id, key=key, value=value[:300],
            source=evidence[:120], confidence=0.8,
        ))
    elif row.value != value:
        row.value = value[:300]
        row.source = evidence[:120]
        row.updated_at = _now()
    # autoflush=False: flush so the next read in this transaction sees it.
    db.flush()


def memory_block(db: DBSession, customer_id: str, max_facts: int = 14) -> str:
    """Compact verified-memory block for the system prompt."""
    rows = db.execute(
        select(CustomerMemory)
        .where(CustomerMemory.customer_id == customer_id)
        .order_by(CustomerMemory.updated_at.desc())
        .limit(max_facts)
    ).scalars().all()
    if not rows:
        return "(no stored facts about this customer yet)"
    return "\n".join(f"- {r.key}: {r.value}" for r in rows)


def recent_messages(db: DBSession, conversation_id: str, limit: int = 12) -> list[dict]:
    rows = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "id": m.id,
            "direction": m.direction,
            "body": m.body,
            # Carried so the owner inbox can render the picture that was sent.
            "msg_type": m.msg_type,
            "image_url": m.image_url or "",
            "created_at": m.created_at.isoformat(),
        }
        for m in reversed(rows)
    ]


def save_summary(db: DBSession, conversation_id: str, summary: str) -> None:
    from app.database import Conversation
    conv = db.get(Conversation, conversation_id)
    if conv is not None:
        conv.summary = summary[:2000]
