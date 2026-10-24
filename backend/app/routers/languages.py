"""Languages API — the ONE registry the console selectors read.

  GET /api/languages   supported languages (code, label, native, flag) + default

The list comes from app/languages.py, the same dict the WhatsApp reply buttons,
the prompt line and every localized string use, so the UI can never drift from
what the agent actually supports.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.languages import DEFAULT_LANGUAGE, LANGUAGE_BUTTONS, language_options

router = APIRouter(prefix="/api/languages", tags=["Languages"])


@router.get("")
async def list_languages() -> dict:
    return {
        "languages": language_options(),
        "default": DEFAULT_LANGUAGE,
        "buttons": [{"id": bid, "title": title} for bid, title in LANGUAGE_BUTTONS],
    }
