"""Transcript listing and detail routes."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from casestack.api.deps import get_case_db

router = APIRouter()


@router.get("/cases/{slug}/transcripts")
def list_transcripts(slug: str, offset: int = 0, limit: int = 100):
    """List all transcripts in the case database."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM transcripts ORDER BY document_id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


@router.get("/cases/{slug}/transcripts/{doc_id}")
def get_transcript(slug: str, doc_id: str):
    """Get a single transcript by its document doc_id (text key)."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # transcripts.document_id is a TEXT column matching documents.doc_id
        row = conn.execute(
            "SELECT * FROM transcripts WHERE document_id = ?", (doc_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Transcript not found")
        return dict(row)
    finally:
        conn.close()


@router.get("/cases/{slug}/media/{doc_id}")
def serve_media(slug: str, doc_id: str):
    """Serve the source media file for playback."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT source_path FROM transcripts WHERE document_id = ?", (doc_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Transcript not found")
    source = row["source_path"]
    if not source or not Path(source).exists():
        raise HTTPException(404, "Media file not found on disk")
    return FileResponse(str(source))
