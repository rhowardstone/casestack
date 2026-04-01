"""Image listing and serving routes."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from casestack.api.deps import get_case_db

router = APIRouter()


@router.get("/cases/{slug}/images")
def list_images(slug: str, offset: int = 0, limit: int | None = None):
    """List extracted images. Pass limit= to paginate; omit for all."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if limit is not None:
            rows = conn.execute(
                "SELECT * FROM extracted_images ORDER BY document_id, page_number LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM extracted_images ORDER BY document_id, page_number",
            ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM extracted_images").fetchone()[0]
        return {"total": total, "images": [dict(r) for r in rows]}
    except Exception:
        return {"total": 0, "images": []}
    finally:
        conn.close()


@router.get("/cases/{slug}/images/{image_id}")
def get_image(slug: str, image_id: int):
    """Get metadata for a single extracted image."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM extracted_images WHERE id = ?", (image_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Image not found")
        return dict(row)
    finally:
        conn.close()


@router.get("/cases/{slug}/images/{image_id}/file")
def serve_image(slug: str, image_id: int):
    """Serve an extracted image file from disk."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT file_path FROM extracted_images WHERE id = ?", (image_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Image not found")
    file_path = Path(row["file_path"])
    if not file_path.exists():
        raise HTTPException(404, "Image file not found on disk")
    return FileResponse(str(file_path))
