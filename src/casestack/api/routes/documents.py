"""Document listing and detail routes."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from casestack.api.deps import get_case_db

router = APIRouter()


@router.get("/cases/{slug}/documents")
def list_documents(slug: str, offset: int = 0, limit: int = 100):
    """List all documents in a case database."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM documents ORDER BY doc_id LIMIT ? OFFSET ?",
        (limit, offset),
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
