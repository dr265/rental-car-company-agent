"""Knowledge base API: multipart upload → parse → index; search preview; delete."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.database import KnowledgeDoc, get_db
from app.knowledge import ALLOWED_EXTENSIONS, delete_document, ingest_document, search_knowledge

log = logging.getLogger("rental.api.knowledge")

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Base"])


@router.get("/documents")
async def list_documents(db: DBSession = Depends(get_db)) -> dict:
    docs = db.execute(
        select(KnowledgeDoc).order_by(KnowledgeDoc.created_at.desc()).limit(200)
    ).scalars().all()
    return {
        "documents": [
            {
                "id": d.id, "filename": d.filename, "size": d.size, "mime": d.mime,
                "status": d.status, "error": d.error or "", "chunk_count": d.chunk_count,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]
    }


@router.post("/upload")
async def upload(file: UploadFile = File(...), db: DBSession = Depends(get_db)) -> dict:
    """Upload a catalogue/policy/FAQ file. Parsed and indexed server-side."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        result = ingest_document(db, file.filename or "upload.bin", data, file.content_type or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return {"status": "ready", **result}


@router.get("/search")
async def search(q: str = "", db: DBSession = Depends(get_db)) -> dict:
    if not q.strip():
        return {"results": []}
    hits = search_knowledge(db, q, limit=6)
    return {"results": [
        {"filename": h["filename"], "score": h["score"], "text": h["text"][:500]} for h in hits
    ]}


@router.delete("/documents/{doc_id}")
async def remove_document(doc_id: str, db: DBSession = Depends(get_db)) -> dict:
    if not delete_document(db, doc_id):
        raise HTTPException(status_code=404, detail="document not found")
    db.commit()
    return {"status": "deleted"}
