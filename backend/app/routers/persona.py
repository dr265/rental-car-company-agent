"""Persona API: read + update the owner-configurable shop profile."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.database import Setting, get_db
from app.persona import PERSONA_FIELDS, get_persona

router = APIRouter(prefix="/api/persona", tags=["Persona"])


@router.get("")
async def read_persona(db: DBSession = Depends(get_db)) -> dict:
    persona = get_persona(db)
    return {"fields": persona.as_dict(), "core_persona_locked": True}


@router.put("")
async def update_persona(payload: dict, db: DBSession = Depends(get_db)) -> dict:
    """Partial update; unknown keys are rejected, values trimmed.

    Core rental behaviour is immutable — there is deliberately no endpoint
    that can edit it.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="body must be a JSON object")
    updates = payload.get("updates") if isinstance(payload.get("updates"), dict) else payload
    applied: list[str] = []
    rejected: list[str] = []
    for key, value in (updates or {}).items():
        if key not in PERSONA_FIELDS:
            rejected.append(key)
            continue
        text = str(value or "").strip()
        db_row = db.get(Setting, f"persona_{key}")
        if db_row is None:
            db_row = Setting(key=f"persona_{key}", value=text)
            db.add(db_row)
        else:
            db_row.value = text
        applied.append(key)
    db.commit()
    persona = get_persona(db)
    return {"status": "updated", "applied": applied, "rejected": rejected, "fields": persona.as_dict()}
