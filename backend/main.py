"""ZoomRideXX Car Rentals WhatsApp AI Agent — backend entrypoint (port 8022).

FastAPI app + Kapso poller + owner console. The deterministic 10-step rental
flow (app/rental_flow.py) answers customers; the LLM covers genuine free-form
questions with live fleet grounding.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    ASSETS_IMAGE_DIR,
    BACKEND_PORT,
    FRONTEND_ORIGIN,
    MEDIA_UPLOAD_DIR,
    MEDIA_URL_PATH,
    STATIC_UI_DIR,
)
from app.database import Base, SessionLocal, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
# The console is for startup, booking and error events only. Per-request
# access logs and httpx's "HTTP Request: ..." lines are pure noise (the Kapso
# poller alone would print one every few seconds forever).
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("zoomride.main")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Starter fleet/FAQ/settings are additive and idempotent: existing
    # vehicles, conversations and bookings are never overwritten.
    try:
        from app.seed import ensure_seed

        with SessionLocal() as db:
            ensure_seed(db)
    except Exception:
        log.exception("starter catalogue seed failed; existing data is untouched")

    # Background Kapso poller: pulls inbound WhatsApp messages every few
    # seconds so the agent works without a public webhook URL (local dev), and
    # as a redundant second delivery path alongside the webhook. Duplicate
    # claims are impossible (processed_messages primary key + OS locks).
    import asyncio

    from app.poller import whatsapp_poll_loop

    poll_task = asyncio.create_task(whatsapp_poll_loop())
    log.info("database ready; Kapso poller + ZoomRideXX rental agent online")
    yield
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="ZoomRideXX Car Rentals AI Assistant", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_ORIGIN,
        # `npm run dev` in frontend/ (port 3020 — 3000 is taken by another app)
        "http://localhost:3020",
        "http://127.0.0.1:3020",
        # the owner console is served by this backend itself
        f"http://localhost:{BACKEND_PORT}",
        f"http://127.0.0.1:{BACKEND_PORT}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import (  # noqa: E402
    admin_auth,
    channels,
    conversations,
    fleet,
    knowledge,
    languages,
    media,
    owner,
    persona,
    system,
    website,
    whatsapp,
)

app.include_router(system.router, prefix="/api")
app.include_router(whatsapp.router)
app.include_router(conversations.router)
app.include_router(knowledge.router)
app.include_router(persona.router)
app.include_router(fleet.router)
app.include_router(owner.router)
app.include_router(channels.router)
app.include_router(media.router)
app.include_router(languages.router)
# Public customer-website API (fleet, quotes, direct bookings, concierge chat)
app.include_router(website.router)
# Owner console login (issues the admin token from ADMIN_EMAIL/ADMIN_PASSWORD)
app.include_router(admin_auth.router)

# Media files the agent sends: served so WhatsApp (link path) and the console
# can fetch them. Two roots keep curated assets separate from console uploads;
# ids in app/media.py address files inside them, never arbitrary paths.
from fastapi.staticfiles import StaticFiles  # noqa: E402

if ASSETS_IMAGE_DIR.is_dir():
    app.mount(f"{MEDIA_URL_PATH}/assets",
              StaticFiles(directory=str(ASSETS_IMAGE_DIR)), name="media_assets")
MEDIA_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount(f"{MEDIA_URL_PATH}/uploads",
          StaticFiles(directory=str(MEDIA_UPLOAD_DIR)), name="media_uploads")


# Service info lives at GET /api/health (and /docs). The root path serves the
# console itself so the agent also works as a plain website.


# Owner console: the exported Next.js UI (frontend/out when built, otherwise
# the legacy single-file console — see app/config.py). The export references
# assets as root-absolute /_next/... paths, so it is mounted at the origin
# ROOT — but AFTER every router above, so API routes always match first and
# static files only catch the remainder. /ui stays as an alias for old links.
if STATIC_UI_DIR.is_dir() and (STATIC_UI_DIR / "index.html").is_file():
    app.mount("/ui", StaticFiles(directory=str(STATIC_UI_DIR), html=True), name="ui")
    app.mount("/", StaticFiles(directory=str(STATIC_UI_DIR), html=True), name="ui_root")


if __name__ == "__main__":
    import uvicorn

    # access_log=False matters in addition to the logger level above: uvicorn's
    # default logging config re-enables the access logger, so the level alone
    # does not silence the per-request lines.
    uvicorn.run(app, host="0.0.0.0", port=BACKEND_PORT, access_log=False)
