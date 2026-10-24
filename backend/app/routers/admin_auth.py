"""Admin console authentication.

  POST /api/admin/login    email + password (from ADMIN_EMAIL / ADMIN_PASSWORD)
                           → returns the admin API token for X-Admin-Token
  POST /api/admin/verify   checks a stored X-Admin-Token and reports validity

The credentials live ONLY in backend/.env — never in source. The token is the
same one require_admin() checks, so a logged-in console keeps working when
ADMIN_AUTH_REQUIRED=1 (full backend enforcement). Bounded per-IP rate limiting
protects the endpoint from credential stuffing.
"""
from __future__ import annotations

import hmac
import logging
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import ADMIN_API_TOKEN, ADMIN_AUTH_REQUIRED, ADMIN_EMAIL, ADMIN_PASSWORD

log = logging.getLogger("rental.api.admin_auth")

router = APIRouter(prefix="/api/admin", tags=["Admin Auth"])

_MAX_ATTEMPTS = 8
_WINDOW_SECONDS = 60.0
_attempts: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else "") or (
        request.client.host if request.client else "unknown")


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    hits = [t for t in _attempts.get(ip, []) if now - t < _WINDOW_SECONDS]
    limited = len(hits) >= _MAX_ATTEMPTS
    if not limited:
        hits.append(now)
    # keep the map bounded
    if len(_attempts) > 500:
        _attempts.clear()
    _attempts[ip] = hits
    return limited


class LoginPayload(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=4, max_length=200)


@router.post("/login")
async def admin_login(payload: LoginPayload, request: Request) -> dict:
    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="too many attempts — try again in a minute")
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="admin login is not configured — set ADMIN_EMAIL and ADMIN_PASSWORD in backend/.env",
        )
    email_ok = hmac.compare_digest(payload.email.strip().lower(), ADMIN_EMAIL.lower())
    password_ok = hmac.compare_digest(payload.password, ADMIN_PASSWORD)
    if not (email_ok and password_ok):
        log.warning("admin login failed from %s", ip)
        raise HTTPException(status_code=401, detail="invalid email or password")

    token = ADMIN_API_TOKEN or secrets.token_urlsafe(32)
    log.info("admin login ok from %s", ip)
    return {
        "ok": True,
        "token": token,
        "email": ADMIN_EMAIL,
        "backend_enforced": ADMIN_AUTH_REQUIRED,
    }


@router.post("/verify")
async def admin_verify(request: Request) -> dict:
    """Is the browser's stored admin token acceptable? Honest in both modes:
    strict compare when ADMIN_API_TOKEN is set, open-dev otherwise."""
    provided = request.headers.get("x-admin-token", "")
    if ADMIN_API_TOKEN:
        return {"valid": hmac.compare_digest(provided, ADMIN_API_TOKEN), "mode": "token"}
    return {"valid": True, "mode": "open"}
