"""Knowledge base: real file upload → parse → chunk → BM25 retrieval.

Supports PDF, DOCX, XLSX, CSV, TXT, JSON and MD. Files are stored on disk under
backend/data/uploads, parsed fully server-side, split into chunks and indexed
for retrieval. `knowledge_block()` returns grounded excerpts that the agent
injects into every prompt — so uploaded catalogues/policies/FAQs are genuinely
used in conversations, not just displayed in the UI.

Document status transitions: uploading → processing → ready | failed (real
states surfaced in the frontend).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.config import UPLOAD_DIR
from app.database import KnowledgeChunk, KnowledgeDoc

log = logging.getLogger("rental.knowledge")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".csv", ".txt", ".json", ".md"}

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "for", "to", "of", "in",
    "on", "at", "with", "is", "are", "was", "were", "be", "been", "it", "this",
    "that", "i", "you", "we", "they", "he", "she", "me", "my", "your", "our",
    "do", "does", "did", "can", "could", "will", "would", "should", "have",
    "has", "had", "not", "no", "yes", "please", "what", "when", "where", "how",
    "why", "is", "am",
}

CHUNK_CHARS = 900
CHUNK_OVERLAP = 120


def tokenize(text: str) -> list[str]:
    return [
        t for t in re.findall(r"\w+", (text or "").lower(), flags=re.UNICODE)
        if t not in STOPWORDS and len(t) > 1
    ]


# --------------------------------------------------------------------------- #
# text extraction per format
# --------------------------------------------------------------------------- #
def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        t = (page.extract_text() or "").strip()
        if t:
            parts.append(t)
    if not parts:
        raise ValueError("no text found in PDF (scanned/image-only PDFs are not supported)")
    return "\n\n".join(parts)


def _extract_docx(path: Path) -> str:
    import docx  # python-docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    if not parts:
        raise ValueError("no text found in DOCX")
    return "\n".join(parts)


def _extract_xlsx(path: Path) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    parts: list[str] = []
    for sheet in wb.worksheets:
        rows = sheet.iter_rows(values_only=True)
        header: list[str] | None = None
        for row in rows:
            cells = ["" if c is None else str(c).strip() for c in row]
            if not any(cells):
                continue
            if header is None:
                header = cells
                parts.append(f"[{sheet.title}] " + " | ".join(cells))
                continue
            parts.append(
                f"[{sheet.title}] "
                + " | ".join(f"{h}: {v}" for h, v in zip(header, cells) if v)
            )
    wb.close()
    if not parts:
        raise ValueError("no readable rows found in XLSX")
    return "\n".join(parts)


def _extract_xls(path: Path) -> str:
    """Read legacy binary .xls files without treating them as UTF-8 text."""
    try:
        import xlrd
    except ImportError as exc:
        raise ValueError("legacy .xls files require the xlrd dependency") from exc
    book = xlrd.open_workbook(str(path), on_demand=True)
    parts: list[str] = []
    try:
        for sheet in book.sheets():
            header: list[str] | None = None
            for row_index in range(sheet.nrows):
                cells = [str(value).strip() for value in sheet.row_values(row_index)]
                if not any(cells):
                    continue
                if header is None:
                    header = cells
                    parts.append(f"[{sheet.name}] " + " | ".join(cells))
                else:
                    parts.append(
                        f"[{sheet.name}] "
                        + " | ".join(f"{h}: {v}" for h, v in zip(header, cells) if v)
                    )
    finally:
        book.release_resources()
    if not parts:
        raise ValueError("no readable rows found in XLS")
    return "\n".join(parts)


def _extract_csv(path: Path) -> str:
    import csv

    parts: list[str] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh)
        header: list[str] | None = None
        for row in reader:
            cells = [c.strip() for c in row]
            if not any(cells):
                continue
            if header is None:
                header = cells
                parts.append(" | ".join(cells))
                continue
            parts.append(" | ".join(f"{h}: {v}" for h, v in zip(header, cells) if v))
    if not parts:
        raise ValueError("no rows found in CSV")
    return "\n".join(parts)


def _extract_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    if not text.strip():
        raise ValueError("file is empty")
    return text


def extract_text(path: Path, ext: str) -> str:
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext == ".xlsx":
        return _extract_xlsx(path)
    if ext == ".xls":
        return _extract_xls(path)
    if ext == ".csv":
        return _extract_csv(path)
    return _extract_text(path)


def chunk_text(text: str) -> list[str]:
    """Fixed-size chunks with overlap so facts spanning boundaries stay retrievable."""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n and len(chunks) < 400:
        end = min(start + CHUNK_CHARS, n)
        if end < n:
            # prefer breaking on a line/sentence boundary
            cut = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
            if cut > start + CHUNK_CHARS // 2:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


# --------------------------------------------------------------------------- #
# ingestion pipeline
# --------------------------------------------------------------------------- #
def ingest_document(db: DBSession, filename: str, data: bytes, mime: str = "") -> dict[str, Any]:
    """Store + parse + index an uploaded file. Raises ValueError on bad input."""
    if not data:
        raise ValueError("empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
    safe_name = Path(filename or "upload.bin").name
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"unsupported file type '{ext or 'unknown'}' — allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    sha = hashlib.sha256(data).hexdigest()
    stored_path = UPLOAD_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{sha[:12]}{ext}"
    stored_path.write_bytes(data)

    doc = KnowledgeDoc(
        filename=safe_name, stored_path=str(stored_path), mime=mime or "",
        size=len(data), status="processing",
    )
    db.add(doc)
    db.flush()

    try:
        text = extract_text(stored_path, ext)
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("no readable content found in file")
        for seq, chunk in enumerate(chunks):
            db.add(KnowledgeChunk(
                doc_id=doc.id, seq=seq, text=chunk[:4000],
                tokens=" ".join(tokenize(chunk))[:4000],
            ))
        doc.chunk_count = len(chunks)
        doc.status = "ready"
        db.flush()
    except Exception as exc:  # noqa: BLE001
        doc.status = "failed"
        doc.error = str(exc)[:500]
        db.flush()
        # Failed documents are not useful to the UI and retaining their raw
        # bytes indefinitely leaks storage. Keep the failure row, remove bytes.
        try:
            stored_path.unlink(missing_ok=True)
        except OSError:
            log.warning("could not remove failed upload %s", stored_path)
        raise
    return {"id": doc.id, "filename": doc.filename, "chunks": doc.chunk_count, "status": doc.status}


def delete_document(db: DBSession, doc_id: str) -> bool:
    doc = db.get(KnowledgeDoc, doc_id)
    if doc is None:
        return False
    db.execute(
        KnowledgeChunk.__table__.delete().where(KnowledgeChunk.doc_id == doc_id)
    )
    try:
        Path(doc.stored_path).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    db.delete(doc)
    return True


# --------------------------------------------------------------------------- #
# BM25 retrieval
# --------------------------------------------------------------------------- #
def search_knowledge(db: DBSession, query: str, limit: int = 5) -> list[dict[str, Any]]:
    terms = tokenize(query)
    if not terms:
        return []
    rows = db.execute(select(KnowledgeChunk)).scalars().all()
    if not rows:
        return []
    # The tokens column is precomputed at ingest time; reuse it instead of
    # re-tokenizing every chunk on every query (O(total_text) regex work per
    # search is the slow path and grows with the knowledge base).
    docs_tokens: list[list[str]] = []
    needs_backfill = False
    for r in rows:
        stored = (r.tokens or "").split()
        if stored:
            docs_tokens.append(stored)
        else:
            docs_tokens.append(tokenize(r.text))
            needs_backfill = True
    if needs_backfill:
        for row, tokens in zip(rows, docs_tokens):
            row.tokens = " ".join(tokens)[:4000]
        db.commit()
    n = len(docs_tokens)
    dfs: dict[str, int] = {}
    for tokens in docs_tokens:
        for t in set(tokens):
            dfs[t] = dfs.get(t, 0) + 1
    avg_len = sum(len(d) for d in docs_tokens) / n
    k1, b = 1.5, 0.75
    results: list[dict[str, Any]] = []
    for row, tokens in zip(rows, docs_tokens):
        score, dl = 0.0, len(tokens) or 1
        for t in terms:
            tf = tokens.count(t)
            df = dfs.get(t, 0)
            if not tf or not df:
                continue
            idf = max(0.01, (n - df + 0.5) / (df + 0.5)) ** 0.5
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(1.0, avg_len)))
        if score > 0:
            doc = db.get(KnowledgeDoc, row.doc_id)
            results.append({
                "chunk_id": row.id,
                "text": row.text,
                "score": score,
                "filename": doc.filename if doc else "unknown",
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    best = results[0]["score"] if results else 0.0
    for r in results:
        r["score"] = round(r["score"] / best, 4) if best else 0.0
    return results[:limit]


def knowledge_block(db: DBSession, query: str, max_chars: int = 1400) -> str:
    """Grounded knowledge excerpts for the agent prompt."""
    if not query.strip():
        return ""
    hits = search_knowledge(db, query, limit=4)
    parts: list[str] = []
    used = 0
    for h in hits:
        snippet = h["text"][:400]
        if used + len(snippet) > max_chars:
            break
        parts.append(f"[{h['filename']}] {snippet}")
        used += len(snippet)
    return "\n\n".join(parts)
