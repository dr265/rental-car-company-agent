"""Media API — the pictures the agent may actually send.

  GET    /api/media                registry: every usable image + its public URL
  GET    /api/media/status          deliverability diagnostics (local vs public)
  POST   /api/media/upload          console "attach image" (multipart, validated)
  DELETE /api/media/{image_id}      remove an UPLOAD (curated assets are kept)

Files live in `backend/assets/images` (shipped) and `<data>/uploads/images`
(writable). Ids are registry slugs — a request can never address an arbitrary
path, and every file is validated (existence, size, real image bytes,
PNG/JPEG/WEBP) before it is listed or sent.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.media import (
    EXTENSION_MIME,
    MediaError,
    delete_upload,
    library,
    media_base,
    public_base_is_reachable,
    resolve,
    save_upload,
    send_image,
)

log = logging.getLogger("rental.api.media")

router = APIRouter(prefix="/api/media", tags=["Media"])


@router.get("")
async def list_media() -> dict:
    """Registry for the console's image picker (ids + ready-to-use URLs)."""
    return {
        "images": library(),
        "media_base_url": media_base(),
        "publicly_reachable": public_base_is_reachable(),
        "supported_formats": sorted({e.lstrip(".") for e in EXTENSION_MIME}),
    }


@router.get("/status")
async def media_status() -> dict:
    """Explains how images will be delivered (used by the console banner)."""
    reachable = public_base_is_reachable()
    images = library()
    return {
        "media_base_url": media_base(),
        "publicly_reachable": reachable,
        "transport": "public link" if reachable else "direct WhatsApp media upload",
        "count": len(images),
        "note": (
            "MEDIA_PUBLIC_BASE_URL is reachable from the internet, so WhatsApp "
            "fetches image links directly."
            if reachable else
            "MEDIA_PUBLIC_BASE_URL is local (dev). Local images are uploaded to "
            "WhatsApp directly by media id instead of a link; set "
            "MEDIA_PUBLIC_BASE_URL to your public host (tunnel/Render) to also "
            "serve links."
        ),
    }


@router.post("/upload")
async def upload_image(file: UploadFile = File(...)) -> dict:
    """Store one console attachment. Rejects anything that is not a real image."""
    data = await file.read()
    entry, why = save_upload(file.filename or "image", data)
    if entry is None:
        raise HTTPException(status_code=422, detail=why or "upload rejected")
    log.info("media upload stored: %s (%d bytes, %s)", entry.id, entry.size, entry.mime)
    return {"status": "stored", "image": entry.as_dict()}


@router.delete("/{image_id}")
async def delete_image(image_id: str) -> dict:
    if resolve(image_id) is None:
        raise HTTPException(status_code=404, detail="image not found")
    if not delete_upload(image_id):
        raise HTTPException(
            status_code=422,
            detail="only images uploaded from the console can be deleted",
        )
    return {"status": "deleted", "id": image_id}


@router.post("/{image_id}/send")
async def send_media(image_id: str, to: str, caption: str = "") -> dict:
    """Send one registry image through the real transport (integration test).

    This is the same code path the agent uses on a customer image request, so a
    successful call here proves the attachment pipeline end-to-end.
    """
    try:
        result = await send_image(image_id, to, caption)
    except MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"send failed: {exc}")
    return {"status": "sent", "via": result.get("via", ""), "to_tail": f"…{to[-4:]}"}
