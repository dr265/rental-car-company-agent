"""SQLAlchemy models + engine. SQLite with WAL for concurrent reads.

Customers, conversations, messages, memory, knowledge, channels, dedupe claims
and webhook audit plus the RENTAL domain:

  Vehicle — real fleet inventory the agent grounds availability/prices on.
  Booking — reservations created ONLY after explicit customer confirmation,
            with a unique reference and overlap protection.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL

if DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.replace("sqlite:///", "", 1)
    from pathlib import Path

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Base(DeclarativeBase):
    pass


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String(36), primary_key=True, default=_uid)
    # E.164 without '+' for lookup stability; display keeps original formatting.
    phone = Column(String(32), unique=True, index=True, nullable=False)
    display_phone = Column(String(32), default="")
    name = Column(String(120), default="")
    whatsapp_name = Column(String(120), default="")
    first_seen_at = Column(DateTime(timezone=True), default=_now)
    last_seen_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)
    # Aggregated free-text notes maintained by the memory system.
    notes = Column(Text, default="")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=_uid)
    customer_id = Column(String(36), ForeignKey("customers.id"), index=True, nullable=False)
    channel = Column(String(24), default="whatsapp")
    # kapso conversation id when available
    external_id = Column(String(64), index=True, default="")
    # running | paused (human handling) | closed
    status = Column(String(16), default="running", index=True)
    # When the chat was handed to staff. Used to auto-release a chat that no
    # human actually answered (see config.HANDOFF_AUTO_RESUME_MINUTES).
    paused_at = Column(DateTime(timezone=True))
    unread_count = Column(Integer, default=0)
    summary = Column(Text, default="")
    # Human handover context for the owner console (additive).
    handoff_reason = Column(String(300), default="")
    handoff_at = Column(DateTime(timezone=True))
    last_message_at = Column(DateTime(timezone=True), default=_now)
    last_message_preview = Column(String(200), default="")
    created_at = Column(DateTime(timezone=True), default=_now)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=_uid)
    conversation_id = Column(String(36), ForeignKey("conversations.id"), index=True, nullable=False)
    # inbound | outbound
    direction = Column(String(8), nullable=False)
    # customer | agent | human  (who actually authored an outbound message)
    sender = Column(String(8), default="agent")
    body = Column(Text, default="")
    # text | image | audio | document | location | interactive | note
    msg_type = Column(String(16), default="text")
    # pending | sent | delivered | read | failed | received (inbound)
    status = Column(String(12), default="received", index=True)
    kapso_message_id = Column(String(80), index=True, default="")
    external_conversation_id = Column(String(64), default="")
    error_detail = Column(Text, default="")
    intent = Column(String(32), default="")
    # Public image URL/path attached to this message (vehicle photo sent to the
    # customer). Empty for text-only turns.
    image_url = Column(String(500), default="")
    created_at = Column(DateTime(timezone=True), default=_now, index=True)

    __table_args__ = (
        Index("ix_messages_dedupe", "kapso_message_id", "direction"),
    )


class CustomerMemory(Base):
    __tablename__ = "customer_memories"

    id = Column(String(36), primary_key=True, default=_uid)
    customer_id = Column(String(36), ForeignKey("customers.id"), index=True, nullable=False)
    # name | budget | pickup_location | vehicle_pref | trip_type | passengers |
    # license | trip_dates | instruction | other | language
    key = Column(String(40), index=True)
    value = Column(String(300))
    source = Column(String(120), default="")  # short evidence snippet
    confidence = Column(Float, default=0.8)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = ({"sqlite_autoincrement": True},)


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"

    id = Column(String(36), primary_key=True, default=_uid)
    filename = Column(String(255), nullable=False)
    stored_path = Column(String(500), default="")
    mime = Column(String(120), default="")
    size = Column(Integer, default=0)
    # uploading | processing | ready | failed
    status = Column(String(16), default="uploading", index=True)
    error = Column(Text, default="")
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_now)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(String(36), primary_key=True, default=_uid)
    doc_id = Column(String(36), ForeignKey("knowledge_docs.id", ondelete="CASCADE"), index=True)
    seq = Column(Integer, default=0)
    text = Column(Text, default="")
    # simple inverted-index support
    tokens = Column(Text, default="")


class Vehicle(Base):
    """Rental fleet item — the ground truth the agent quotes.

    Managed from the console (Fleet tab) or imported from a CSV/XLSX catalogue
    file. Never seeded with fake data: an empty table simply means the agent
    answers availability/price questions with "let me confirm with the team".
    """

    __tablename__ = "vehicles"

    id = Column(String(36), primary_key=True, default=_uid)
    code = Column(String(64), unique=True, index=True, nullable=False)  # e.g. CAR-SWIFT-01
    name = Column(String(200), nullable=False)
    category = Column(String(80), default="")  # hatchback, sedan, suv, luxury, tempo, bike
    transmission = Column(String(24), default="")  # manual | automatic
    fuel = Column(String(24), default="")  # petrol | diesel | cng | electric
    seats = Column(Integer)
    price_per_day = Column(Float)
    price_per_hour = Column(Float)
    # Fixed-duration packages from the published rate card. NULL means the
    # package is not offered for that vehicle.
    price_6h = Column(Float)
    price_12h = Column(Float)
    price_24h = Column(Float)
    deposit = Column(Float)  # refundable security deposit
    driver_fee_per_day = Column(Float)  # vehicle-specific chauffeur fee (optional)
    mileage_limit_per_day = Column(Float)  # km included per day
    extra_km_charge = Column(Float)  # per extra km
    available = Column(Integer, default=1)  # 1 listed/available, 0 parked/withdrawn
    image_url = Column(String(500), default="")
    description = Column(Text, default="")
    location = Column(String(200), default="")  # where it can be picked up
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class Booking(Base):
    """A rental reservation. Created ONLY after explicit customer confirmation.

    Lifecycle: draft → confirmed → (completed | cancelled).
    • reference (RC-XXXXXX) is generated on CONFIRM and is unique.
    • overlap protection: a vehicle can never have two confirmed/active
      bookings whose [start_at, end_at) windows intersect.
    • source_message_id makes confirmation idempotent: replaying the same
      WhatsApp "Confirm" tap can never create a second booking.
    """

    __tablename__ = "bookings"

    id = Column(String(36), primary_key=True, default=_uid)
    reference = Column(String(24), unique=True, index=True, nullable=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), index=True, nullable=False)
    vehicle_id = Column(String(36), ForeignKey("vehicles.id"), index=True, nullable=False)
    # draft | confirmed | cancelled | completed
    status = Column(String(16), default="draft", index=True)
    start_at = Column(DateTime(timezone=True))
    end_at = Column(DateTime(timezone=True))
    pickup_location = Column(String(200), default="")
    dropoff_location = Column(String(200), default="")
    with_driver = Column(Integer, default=0)  # 1 = chauffeur-driven
    days = Column(Integer, default=1)
    # Package the customer chose: 6, 12 or 24 hours. NULL for legacy day quotes.
    duration_hours = Column(Integer)
    drive_mode = Column(String(16), default="")  # self | chauffeur
    handover = Column(String(16), default="")    # hub | doorstep
    kyc_mode = Column(String(24), default="")    # whatsapp | handover
    price_per_day = Column(Float, default=0)
    driver_fee = Column(Float, default=0)
    delivery_fee = Column(Float, default=0)
    base_amount = Column(Float, default=0)
    total_estimate = Column(Float, default=0)
    deposit = Column(Float, default=0)
    currency = Column(String(8), default="₹")
    notes = Column(Text, default="")
    # WhatsApp message id of the confirming tap → idempotent confirmation
    source_message_id = Column(String(80), index=True, default="")
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)
    confirmed_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_bookings_vehicle_window", "vehicle_id", "status", "start_at", "end_at"),
    )


class FAQ(Base):
    """Owner-managed FAQ answers the assistant can rely on verbatim."""

    __tablename__ = "faqs"

    id = Column(String(36), primary_key=True, default=_uid)
    question = Column(String(300), nullable=False)
    answer = Column(Text, nullable=False)
    category = Column(String(80), default="")
    sort_order = Column(Integer, default=0)
    active = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class Channel(Base):
    """WhatsApp channel added from the console ('+' button on Connection).

    Credentials are encrypted at rest (Fernet, key derived from the webhook
    secret). Exactly one channel may be the primary command center — its
    inbound messages route to the agent and replies go out through it.
    """

    __tablename__ = "channels"

    id = Column(String(36), primary_key=True, default=_uid)
    name = Column(String(120), nullable=False)
    provider = Column(String(24), nullable=False)  # kapso | meta | generic | twilio
    phone_number = Column(String(32), default="")
    credentials_enc = Column(Text, default="")
    # connecting | connected | error | disconnected
    status = Column(String(16), default="connecting", index=True)
    enabled = Column(Integer, default=1)
    is_primary = Column(Integer, default=0)
    last_error = Column(Text, default="")
    last_checked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_now)


class Setting(Base):
    """Key/value app settings: persona fields, agent running flag, etc."""

    __tablename__ = "settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class ProcessedMessage(Base):
    """Cross-process claim table: one row per WhatsApp message id ever handled.

    The primary key makes the INSERT the atomic "claim": when two backend
    processes poll the same WhatsApp number, only the first process to insert
    wins and the other skips the message. This is what makes duplicate replies
    impossible even with two instances on the SAME database. (Two separate
    databases are prevented by the shared per-number poller lock — see
    app/poller.py.)
    """

    __tablename__ = "processed_messages"

    wa_message_id = Column(String(80), primary_key=True)
    conversation_id = Column(String(36), default="")
    processed_at = Column(DateTime(timezone=True), default=_now, index=True)


class WebhookEvent(Base):
    """Raw inbound webhook log for audit + duplicate protection."""

    __tablename__ = "webhook_events"

    id = Column(String(36), primary_key=True, default=_uid)
    provider = Column(String(16), default="kapso")
    event_type = Column(String(48), default="")
    message_id = Column(String(80), index=True, default="")
    payload_json = Column(Text, default="")
    processed = Column(Boolean, default=False)
    error = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_now, index=True)


Base.metadata.create_all(bind=engine)


def _migrate_missing_columns() -> None:
    """Additive column migrations for databases created by older builds.

    `create_all` only creates missing TABLES, never missing COLUMNS. Each entry
    is applied only when the column is genuinely absent (PRAGMA table_info),
    which makes the whole thing idempotent and safe on every start-up.
    """
    wanted = {
        "messages": {"image_url": "VARCHAR(500) NOT NULL DEFAULT ''"},
        "conversations": {
            "paused_at": "DATETIME",
            "handoff_reason": "VARCHAR(300) NOT NULL DEFAULT ''",
            "handoff_at": "DATETIME",
        },
        "vehicles": {
            "price_6h": "FLOAT",
            "price_12h": "FLOAT",
            "price_24h": "FLOAT",
        },
        "bookings": {
            "source_message_id": "VARCHAR(80) NOT NULL DEFAULT ''",
            "duration_hours": "INTEGER",
            "drive_mode": "VARCHAR(16) NOT NULL DEFAULT ''",
            "handover": "VARCHAR(16) NOT NULL DEFAULT ''",
            "kyc_mode": "VARCHAR(24) NOT NULL DEFAULT ''",
        },
    }
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        for table, columns in wanted.items():
            existing = {
                str(row[1])
                for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            }
            if not existing:
                continue
            for column, ddl in columns.items():
                if column in existing:
                    continue
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


_migrate_missing_columns()
