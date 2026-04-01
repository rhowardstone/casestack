"""Document listing and detail routes."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from casestack.api.deps import get_case_db

router = APIRouter()


@router.get("/cases/{slug}/documents")
def list_documents(
    slug: str,
    offset: int = 0,
    limit: int | None = None,
    sort: str = "doc_id",
    date_from: str | None = None,
    date_to: str | None = None,
):
    """List all documents. sort= accepts 'doc_id' (default) or 'date'.
    Optionally filter by date_from / date_to (YYYY-MM-DD).
    """
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    order = "date" if sort == "date" else "doc_id"
    where_clauses = []
    params: list = []
    if date_from:
        where_clauses.append("date >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("date <= ?")
        params.append(date_to)
    where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    if limit is not None:
        rows = conn.execute(
            f"SELECT * FROM documents {where} ORDER BY {order} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM documents {where} ORDER BY {order}",
            params,
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/cases/{slug}/documents/{doc_id}")
def get_document(slug: str, doc_id: str):
    """Get a single document by its doc_id."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Document not found")
    return dict(row)


@router.get("/cases/{slug}/documents/{doc_id}/file")
def get_document_file(slug: str, doc_id: str):
    """Serve the original document file (PDF, EML, etc.) for inline viewing."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT file_path FROM documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    conn.close()
    if not row or not row["file_path"]:
        raise HTTPException(404, "File path not recorded for this document")
    file_path = Path(row["file_path"])
    if not file_path.exists():
        raise HTTPException(404, f"File not found on disk: {file_path}")
    suffix = file_path.suffix.lower()
    _MEDIA_TYPES = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".avi": "video/x-msvideo",
        ".eml": "message/rfc822",
    }
    media_type = _MEDIA_TYPES.get(suffix, "application/octet-stream")
    return FileResponse(str(file_path), media_type=media_type)


@router.get("/cases/{slug}/documents/{doc_id}/pages")
def get_document_pages(slug: str, doc_id: str):
    """Get all pages for a document, ordered by page number."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # Look up the integer document PK from the text doc_id
    doc = conn.execute(
        "SELECT id FROM documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if not doc:
        conn.close()
        raise HTTPException(404, "Document not found")
    rows = conn.execute(
        "SELECT * FROM pages WHERE document_id = ? ORDER BY page_number",
        (doc["id"],),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
