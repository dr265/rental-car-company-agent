"""Credential encryption for stored channel/sheet connections (Fernet)."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os

log = logging.getLogger("rental.crypto")


def _fernet():
    from cryptography.fernet import Fernet

    master = (os.getenv("JEWEL_MASTER_KEY") or os.getenv("KAPSO_WEBHOOK_SECRET") or "").strip()
    if not master:
        # Never silently encrypt credentials with a public, predictable default.
        # Local channel setup must explicitly configure a stable secret too.
        raise RuntimeError(
            "credential encryption is unavailable: set JEWEL_MASTER_KEY "
            "or KAPSO_WEBHOOK_SECRET in backend/.env"
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(master.encode()).digest())
    return Fernet(key)


def encrypt_json(obj) -> str:
    return _fernet().encrypt(json.dumps(obj).encode()).decode()


def decrypt_json(token: str | None) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except Exception:  # noqa: BLE001
        log.warning("Failed to decrypt stored credentials (key changed?)")
        return {}
