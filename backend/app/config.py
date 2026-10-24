"""Central settings — all secrets come from environment variables.

Rental Car WhatsApp AI Agent. Kapso transport variables, the LLM failover
chain, media and handoff settings live here, plus a small rental-business
block (fees, policies) at the end.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Development: everything lives in the repo (backend/, backend/data, .env).
# Packaged exe (PyInstaller, sys.frozen): the source tree does not exist —
# writable data goes to %LOCALAPPDATA%\RentalCarAgent and the .env is read
# from next to the .exe (optional) or the data directory.
if getattr(sys, "frozen", False):
    _app_dir = Path(os.getenv("APPDATA") or Path.home()) / "RentalCarAgent"
    _app_dir.mkdir(parents=True, exist_ok=True)
    DATA_BASE = _app_dir
    _exe_dir = Path(sys.executable).resolve().parent
    load_dotenv(_exe_dir / ".env")
    load_dotenv(_app_dir / ".env")
    _static_ui_default = _exe_dir / "ui"
else:
    DATA_BASE = BACKEND_ROOT
    _static_ui_default = BACKEND_ROOT / "console"

load_dotenv(BACKEND_ROOT / ".env")

def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()

# --- WhatsApp transport (Kapso) -------------------------------------------- #
KAPSO_API_KEY = _env("KAPSO_API_KEY")
KAPSO_PHONE_NUMBER_ID = _env("KAPSO_PHONE_NUMBER_ID")
KAPSO_WEBHOOK_SECRET = _env("KAPSO_WEBHOOK_SECRET")

PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "http://localhost:8022").rstrip("/")

BACKEND_PORT = int(_env("BACKEND_PORT", "8022"))
# Next.js console dev server (`npm run dev` in frontend/). Port 3020 avoids
# clashing with other local dev servers already using 3000/3010.
FRONTEND_ORIGIN = _env("FRONTEND_ORIGIN", "http://localhost:3020")

DATA_DIR = DATA_BASE / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_database_url = _env("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'rental_agent.db').as_posix()}")
# A relative SQLite URL is otherwise resolved against whichever directory starts
# uvicorn (the launcher uses backend/, while tests and IDEs often use the repo
# root). Resolve local paths once so every process opens the same database.
if _database_url.startswith("sqlite:///"):
    _sqlite_path = Path(_database_url.removeprefix("sqlite:///"))
    if not _sqlite_path.is_absolute():
        base = DATA_BASE if getattr(sys, "frozen", False) else BACKEND_ROOT
        _sqlite_path = base / _sqlite_path
    _sqlite_path = _sqlite_path.resolve()
    DATABASE_URL = f"sqlite:///{_sqlite_path.as_posix()}"
else:
    DATABASE_URL = _database_url

# The console is intentionally backwards-compatible for local development, but
# can be protected with a shared admin token when exposed beyond localhost.
ADMIN_API_TOKEN = _env("ADMIN_API_TOKEN")
ADMIN_AUTH_REQUIRED = _env("ADMIN_AUTH_REQUIRED", "0").lower() in {"1", "true", "yes", "on"}

# Owner console login (/console). Credentials live ONLY in backend/.env — the
# login endpoint (app/routers/admin_auth.py) compares against these and issues
# the admin token. Leave blank to disable the login endpoint entirely.
ADMIN_EMAIL = _env("ADMIN_EMAIL")
ADMIN_PASSWORD = _env("ADMIN_PASSWORD")

# --------------------------------------------------------------------------- #
# LLM providers — failover chain shared by every deployment.
# Same env var names, same base URLs, same model ids, same failover order, so
# no new API credentials are needed. Current order:
#   1. cleanapis  — deepseek-v4-flash-0731 (light) + claude-sonnet-5 (complex)
#   2. manifest   — gateway 'auto' (error-strings detected and failed over)
#   3. apinex     — deepseek-v4-flash (hard 5 req/min limit → short cooldown)
#   4. apiqik     — late fallback
#   5. axqua      — late fallback
# A failing provider is skipped on a cooldown (see app/llm.py). KIE_* keys that
# exist in .env are deliberately left out of this chain.
# --------------------------------------------------------------------------- #
AI_PROXY_URL = _env("AI_PROXY_URL").rstrip("/")
AI_PROXY_TOKEN = _env("AI_PROXY_TOKEN")

# --------------------------------------------------------------------------- #
# Images the agent can actually SEND (WhatsApp media). Files live INSIDE the
# project, addressed by registry id, never by absolute path. assets/images + data/uploads/images are both scanned
# and served over HTTP; when the base URL is not internet-reachable the agent
# uploads the bytes directly (Cloud API media id) instead of sending a link.
# --------------------------------------------------------------------------- #
if getattr(sys, "frozen", False):
    _bundle_dir = Path(getattr(sys, "_MEIPASS", _exe_dir))
    ASSETS_IMAGE_DIR = Path(_env("ASSETS_IMAGE_DIR", str(_bundle_dir / "assets" / "images")))
else:
    ASSETS_IMAGE_DIR = Path(_env("ASSETS_IMAGE_DIR", str(BACKEND_ROOT / "assets" / "images")))

MEDIA_UPLOAD_DIR = UPLOAD_DIR / "images"
MEDIA_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MEDIA_PUBLIC_BASE_URL = _env("MEDIA_PUBLIC_BASE_URL").rstrip("/")
MEDIA_URL_PATH = _env("MEDIA_URL_PATH", "/media") or "/media"
MAX_IMAGE_BYTES = max(1024, int(_env("MAX_IMAGE_BYTES", str(8 * 1024 * 1024))))
# Vehicle photos are ALWAYS sent when a specific vehicle is quoted (no gate).
MEDIA_DIRECT_UPLOAD = _env("MEDIA_DIRECT_UPLOAD", "1").lower() in {"1", "true", "yes", "on"}

# --------------------------------------------------------------------------- #
# Human handoff safety net
# --------------------------------------------------------------------------- #
HANDOFF_AUTO_RESUME_MINUTES = max(0, int(_env("HANDOFF_AUTO_RESUME_MINUTES", "30")))

# Fleet desk numbers that receive an instant alert for every confirmed booking.
# Comma/space separated; digits are normalised before sending. Overridable from
# backend/.env so the owner can change them without touching code.
OWNER_WHATSAPP_NUMBERS: tuple[str, ...] = tuple(
    part for part in re.split(r"[,\s;]+", _env(
        "OWNER_WHATSAPP_NUMBERS", "9179642928,9516108857")) if part
)

# The WhatsApp Business number customers chat with ("Book on WhatsApp" deep
# links on the website). Digits only, WITH country code. Defaults to the fleet
# desk's first number with the India prefix — the same chat link the project
# has always published — so the website never invents a number.
WA_BUSINESS_NUMBER = _env("WA_BUSINESS_NUMBER") or f"91{OWNER_WHATSAPP_NUMBERS[0]}"

# Static UI directory: prefer the Next.js export (frontend/out, produced by
# `npm run build` in frontend/) so the console is the full SARA-style website;
# fall back to the legacy single-file console (backend/console) when the
# frontend has not been built yet. STATIC_UI_DIR overrides both.
if getattr(sys, "frozen", False):
    _ui_export = _exe_dir / "ui"
else:
    _ui_export = BACKEND_ROOT.parent / "frontend" / "out"
_static_ui_default = _ui_export if (_ui_export / "index.html").is_file() else _static_ui_default
STATIC_UI_DIR = Path(_env("STATIC_UI_DIR", str(_static_ui_default)))

LLM_PROVIDERS: list[dict] = [
    {
        "name": "cleanapis",
        "base_url": _env("CLEANAPIS_BASE_URL", "https://cleanapis.com/v1"),
        "api_key": _env("CLEANAPIS_API_KEY"),
        "models": {
            "light": "deepseek-v4-flash-0731",
            "complex": "claude-sonnet-5",
        },
    },
    {
        "name": "manifest",
        "base_url": _env("MANIFEST_BASE_URL", "https://app.manifest.build/v1"),
        "api_key": _env("MANIFEST_API_KEY"),
        "models": {
            "light": "auto",
            "complex": "auto",
        },
    },
    {
        "name": "apinex",
        "base_url": _env("APINEX_BASE_URL", "https://api.apinex.bond/v1"),
        "api_key": _env("APINEX_API_KEY"),
        "models": {
            "light": "deepseek-v4-flash",
            "complex": "claude-sonnet-5",
        },
    },
    {
        "name": "apiqik",
        "base_url": _env("APIQIK_BASE_URL", "https://api.apiqik.com/v1"),
        "api_key": _env("APIQIK_API_KEY"),
        "models": {
            "light": "gemini-2.5-flash-lite",
            "complex": "claude-sonnet-5",
        },
    },
    {
        "name": "axqua",
        "base_url": _env("AXQUA_BASE_URL", "https://axqua.com/v1"),
        "api_key": _env("AXQUA_API_KEY"),
        "models": {
            "light": "qwen3.8-flash",
            "complex": "claude-sonnet-5",
        },
    },
]

# Cooldown seconds after a provider failure before it is retried.
LLM_COOLDOWN_SECONDS = 120
LLM_TIMEOUT_SECONDS = 45
LLM_TOTAL_TIMEOUT_SECONDS = max(LLM_TIMEOUT_SECONDS, int(_env("LLM_TOTAL_TIMEOUT_SECONDS", "60")))
LLM_MAX_ATTEMPTS = max(1, int(_env("LLM_MAX_ATTEMPTS", "3")))

def llm_configured() -> bool:
    return any(p["api_key"] for p in LLM_PROVIDERS)

# --------------------------------------------------------------------------- #
# Rental business rules (agent grounding + pricing; owner-tunable via .env)
# --------------------------------------------------------------------------- #
RENTAL_CURRENCY = _env("RENTAL_CURRENCY", "₹")
# Chauffeur-driven fee per day when a vehicle row does not define its own.
RENTAL_DRIVER_FEE_PER_DAY = max(0.0, float(_env("RENTAL_DRIVER_FEE_PER_DAY", "800") or 0))
# Airport pickup / doorstep delivery fee (applied only when requested).
RENTAL_DELIVERY_FEE = max(0.0, float(_env("RENTAL_DELIVERY_FEE", "500") or 0))
# Self-drive rentals require a valid driving licence unless switched off.
RENTAL_LICENSE_REQUIRED = _env("RENTAL_LICENSE_REQUIRED", "1").lower() in {"1", "true", "yes", "on"}
# Refundable security deposit is ALWAYS shown separately, never in the total.
RENTAL_DEPOSIT_REQUIRED = _env("RENTAL_DEPOSIT_REQUIRED", "1").lower() in {"1", "true", "yes", "on"}
# Sanity bound so a mis-parsed date can never book a vehicle for years.
RENTAL_MAX_BOOKING_DAYS = max(1, int(_env("RENTAL_MAX_BOOKING_DAYS", "60")))
# Minimum lead time (hours) between now and a self-service booking start.
RENTAL_MIN_LEAD_HOURS = max(0, int(_env("RENTAL_MIN_LEAD_HOURS", "2")))
