"""Kapso inbound poller (same pattern as SARA's Zernio inbox poller).

Kapso delivers inbound messages via webhook, but a webhook needs a public
HTTPS URL. For local development (and as a resilient fallback in production)
this poller pulls new inbound messages directly from Kapso's messages API:

    GET /meta/whatsapp/v24.0/{phone_number_id}/messages?direction=inbound&since=...

Every fetched message is deduped by WhatsApp message id (against the local DB,
so webhook + poller double delivery is safe) and dispatched into the same
agent.handle_inbound pipeline as webhooks. The loop respects the global
RUN/PAUSE switch: while paused, messages are still fetched and stored (so the
owner sees them) but the agent does not reply.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from app.config import LLM_PROVIDERS  # noqa: F401  (import keeps config loaded)
from app.database import Message, ProcessedMessage, SessionLocal, Setting
from app.kapso import META_API, InboundMessage, kapso

log = logging.getLogger("rental.poller")

# A webhook is the primary delivery path; this loop is the local-dev / fallback
# safety net, so polling every second only created log and API noise. Three
# seconds keeps replies snappy without hammering Kapso (override with
# KAPSO_POLL_SECONDS in .env).
POLL_INTERVAL_SECONDS = max(1.0, float(os.getenv("KAPSO_POLL_SECONDS", "3")))
# On first ever start, only pick up messages newer than this window.
FIRST_RUN_WINDOW = timedelta(minutes=10)
# Never replay a very old checkpoint on startup (for example, the legacy rental
# agent last ran a week ago). WhatsApp only allows free-form replies inside the
# 24-hour customer service window, so older catch-up cannot be answered anyway.
MAX_CATCHUP = timedelta(hours=float(os.getenv("POLL_MAX_CATCHUP_HOURS", "24")))
# Overlap between polls so a message that lands while a fetch is in flight is
# never skipped: always re-read a little further back than the last checkpoint.
POLL_OVERLAP = timedelta(seconds=2)
LAST_POLL_KEY = "wa_last_poll_iso"


def clamp_checkpoint(dt: datetime, now: datetime | None = None) -> datetime:
    """Keep a stale poll checkpoint inside the safe catch-up window."""
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    floor = now - MAX_CATCHUP
    if dt < floor:
        log.warning(
            "poll checkpoint %s is older than the %s catch-up limit — starting from %s",
            dt.isoformat(), MAX_CATCHUP, floor.isoformat(),
        )
        return floor
    return dt


def agent_running() -> bool:
    """Global RUN/PAUSE switch (persisted in settings, default = running)."""
    db = SessionLocal()
    try:
        row = db.get(Setting, "agent_running")
        return (row.value if row else "1") != "0"
    finally:
        db.close()


def set_agent_running(running: bool) -> None:
    db = SessionLocal()
    try:
        row = db.get(Setting, "agent_running")
        if row is None:
            db.add(Setting(key="agent_running", value="1" if running else "0"))
        else:
            row.value = "1" if running else "0"
        db.commit()
    finally:
        db.close()


def _last_poll(db: SessionLocal) -> datetime:
    row = db.get(Setting, LAST_POLL_KEY)
    if row and row.value:
        try:
            dt = datetime.fromisoformat(row.value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return clamp_checkpoint(dt)
        except ValueError:
            pass
    return datetime.now(timezone.utc) - FIRST_RUN_WINDOW


def _message_seen(db: SessionLocal, wa_message_id: str) -> bool:
    if not wa_message_id:
        return False
    row = db.execute(
        select(Message.id).where(Message.kapso_message_id == wa_message_id)
    ).first()
    return row is not None


def claim_message(db, wa_message_id: str, conversation_id: str = "") -> bool:
    """Atomically claim a WhatsApp message id across ALL backend processes.

    The primary-key INSERT is the claim: with two backends polling the same
    number (dev + packaged exe), exactly one wins and the other returns False
    — so a customer can never receive the same reply twice.
    """
    if not wa_message_id:
        return True  # nothing to claim (e.g. simulated messages)
    db.add(ProcessedMessage(wa_message_id=wa_message_id, conversation_id=conversation_id))
    try:
        db.commit()
        return True
    except Exception:  # noqa: BLE001 — PK conflict = another worker claimed it
        db.rollback()
        return False


# --------------------------------------------------------------------------- #
# single-poller guard: only ONE backend process may run the polling loop
# --------------------------------------------------------------------------- #
_POLL_LOCK_NAME = "poller.lock"
_poll_lock_fd = None


def _try_acquire_poller_lock() -> bool:
    """Best-effort OS file lock in the data directory.

    Returns True when THIS process owns the polling loop. A second backend
    (accidental double start, or exe running beside dev) detects the held lock
    and serves API traffic only — duplicate pollers were the cause of
    customers receiving every reply two or three times.
    """
    global _poll_lock_fd
    if _poll_lock_fd is not None:
        return True
    try:
        from app.config import DATA_DIR

        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, _POLL_LOCK_NAME)
        fd = os.open(path, os.O_CREAT | os.O_RDWR)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            log.warning("another backend instance owns the poller lock — "
                        "this instance will serve API traffic only")
            return False
        os.write(fd, str(os.getpid()).encode()[:20])
        _poll_lock_fd = fd
        return True
    except Exception:  # noqa: BLE001 — never block the API over a lock issue
        log.exception("poller lock acquisition failed; continuing single-loop")
        return True


# --------------------------------------------------------------------------- #
# shared cross-project number lock: only ONE agent backend may poll + reply on
# the same WhatsApp business number at a time. Without this guard two running
# backends would each see every inbound message and the customer would get
# double replies (the per-database ProcessedMessage claim cannot dedupe
# across two separate databases).
# --------------------------------------------------------------------------- #
_shared_number_lock_fd = None


def _try_acquire_shared_number_lock() -> bool:
    r"""Best-effort OS lock in a NEUTRAL shared location (per phone-number id).

    The lock file lives under %LOCALAPPDATA%\WhatsAppAgentShared so separate
    projects that share the same WhatsApp number contend on the SAME path.
    Returns True when THIS process may poll/send for this number. Any failure
    is non-fatal (return True) — the guard is a safety net, never a blocker for
    the API.
    """
    # Allow disabling the cross-project lock via env var (for dev when both
    # agents share the same WhatsApp number)
    if os.getenv("SHARED_NUMBER_LOCK", "1") == "0":
        return True
        
    global _shared_number_lock_fd
    if _shared_number_lock_fd is not None:
        return True
    if not kapso.phone_number_id:
        return True  # nothing to contend on (no credentials configured)
    try:
        base = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "WhatsAppAgentShared"
        base.mkdir(parents=True, exist_ok=True)
        digits = re.sub(r"[^0-9]", "", kapso.phone_number_id) or "default"
        path = base / f"kapso_{digits}.lock"
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            log.warning(
                "another agent backend already owns WhatsApp "
                "number ...%s — this instance will NOT poll or auto-reply",
                kapso.phone_number_id[-4:],
            )
            return False
        os.write(fd, str(os.getpid()).encode()[:20])
        _shared_number_lock_fd = fd
        return True
    except Exception:  # noqa: BLE001 — never block the API over a lock issue
        log.exception("shared number lock check failed; continuing")
        return True


async def fetch_inbound_since(since: datetime) -> list[InboundMessage]:
    """Pull inbound messages from the Kapso API and normalize them."""
    params = {
        "direction": "inbound",
        "since": since.isoformat(),
        "limit": 100,
    }
    headers = kapso._headers()  # reuse the transport's auth headers (env-configured)
    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0)) as client:
        resp = await client.get(
            f"{META_API}/{kapso.phone_number_id}/messages", params=params, headers=headers
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Kapso messages fetch {resp.status_code}: {resp.text[:200]}")

    items = (resp.json() or {}).get("data") or []
    parsed: list[InboundMessage] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        k = item.get("kapso") or {}
        # Same normalizer as the webhook path (payload shapes are identical).
        msg = kapso._parse_single({
            "message": item,
            "conversation": {
                "id": k.get("whatsapp_conversation_id") or "",
                "contact_name": k.get("contact_name") or "",
                "phone_number": item.get("from") or "",
            },
        })
        if msg is not None:
            parsed.append(msg)
    return parsed


async def poll_once() -> int:
    """One poll pass. Returns the number of NEW messages dispatched."""
    if not kapso.configured:
        return 0
    db = SessionLocal()
    try:
        since = _last_poll(db) - POLL_OVERLAP
    finally:
        db.close()

    messages = await fetch_inbound_since(since)
    dispatched = 0
    for inbound in messages:
        db = SessionLocal()
        try:
            if _message_seen(db, inbound.message_id):
                continue
        finally:
            db.close()
        # NOTE: the atomic cross-process claim lives in agent.handle_inbound
        # (single place = no double-claim that would drop a message).
        await _dispatch(inbound)
        dispatched += 1
    return dispatched


async def _dispatch(inbound: InboundMessage) -> None:
    try:
        from app.agent import agent

        await agent.handle_inbound(inbound)
    except Exception:  # noqa: BLE001 — one bad message must never kill the loop
        log.exception("poller dispatch failed for message %s", inbound.message_id)


async def whatsapp_poll_loop() -> None:
    """Long-lived poller task started by the backend lifespan."""
    if not _try_acquire_poller_lock():
        log.warning("poller disabled in this instance (single-instance guard)")
        return
    if not _try_acquire_shared_number_lock():
        log.warning(
            "poller disabled: another agent backend owns this WhatsApp number "
            "(stop it first, or run the two businesses on separate numbers)"
        )
        log.warning("FALLBACK: Running poller anyway for development (set SHARED_NUMBER_LOCK=0 to suppress)")
        # For development, allow running even if another backend owns the number
        import os
        if os.getenv("SHARED_NUMBER_LOCK", "1") != "0":
            return
    log.info("Kapso poller started (interval %ss)", POLL_INTERVAL_SECONDS)
    while True:
        try:
            if kapso.configured:
                await poll_once()
                db = SessionLocal()
                try:
                    row = db.get(Setting, LAST_POLL_KEY)
                    now = datetime.now(timezone.utc).isoformat()
                    if row is None:
                        db.add(Setting(key=LAST_POLL_KEY, value=now))
                    else:
                        row.value = now
                    db.commit()
                finally:
                    db.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("poll pass failed (will retry): %s", exc)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
