"""Unified search across all data types in a case."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from casestack.api.deps import get_app_state

router = APIRouter()


def _get_case_db(slug: str) -> Path:
    """Find the SQLite DB for a case."""
    state = get_app_state()
    case = state.get_case(slug)
    if not case:
        raise HTTPException(404, "Case not found")
    output_dir = Path(case["output_dir"])
    db_path = output_dir / f"{slug}.db"
    if not db_path.exists():
        raise HTTPException(404, "Database not found. Run ingest first.")
    return db_path


@router.get("/cases/{slug}/search")
def search(slug: str, q: str = Query(...), type: str = Query("all"),
           offset: int = 0, limit: int = 50):
    """Unified search across pages, transcripts, images, entities."""
    db_path = _get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    results = []
    total = 0
    requested_types = (
        {"pages", "transcripts", "images"}
        if type == "all"
        else set(type.split(","))
    )

    # Search pages via FTS5
    if "pages" in requested_types:
        try:
            rows = conn.execute("""
                SELECT d.doc_id, d.title, p.page_number,
                       snippet(pages_fts, 0, '<mark>', '</mark>', '...', 64) as snippet,
                       rank
                FROM pages_fts
                JOIN pages p ON p.id = pages_fts.rowid
                JOIN documents d ON d.id = p.document_id
                WHERE pages_fts MATCH ?
                ORDER BY rank
                LIMIT ? OFFSET ?
            """, (q, limit, offset)).fetchall()
            for row in rows:
                results.append({
                    "type": "page",
                    "document_id": row["doc_id"],
                    "title": row["title"],
                    "page_number": row["page_number"],
                    "snippet": row["snippet"],
                    "rank": row["rank"],
                })
            count_row = conn.execute(
                "SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH ?", (q,)
            ).fetchone()
            total += count_row[0]
        except Exception:
            pass  # FTS table may not exist

    # Search transcripts via FTS5
    if "transcripts" in requested_types:
        try:
            rows = conn.execute("""
                SELECT t.document_id,
                       snippet(transcripts_fts, 0, '<mark>', '</mark>', '...', 64) as snippet,
                       rank
                FROM transcripts_fts
                JOIN transcripts t ON t.rowid = transcripts_fts.rowid
                WHERE transcripts_fts MATCH ?
                LIMIT ? OFFSET ?
            """, (q, limit, offset)).fetchall()
            for row in rows:
                results.append({
                    "type": "transcript",
                    "document_id": row["document_id"],
                    "snippet": row["snippet"],
                    "rank": row["rank"],
                })
            count_row = conn.execute(
                "SELECT COUNT(*) FROM transcripts_fts WHERE transcripts_fts MATCH ?",
                (q,),
            ).fetchone()
            total += count_row[0]
        except Exception:
            pass

    # Search image descriptions via FTS5
    if "images" in requested_types:
        try:
            rows = conn.execute("""
                SELECT i.document_id, i.page_number, i.file_path, i.description,
                       snippet(images_fts, 0, '<mark>', '</mark>', '...', 64) as snippet,
                       rank
                FROM images_fts
                JOIN extracted_images i ON i.id = images_fts.rowid
                WHERE images_fts MATCH ?
                LIMIT ? OFFSET ?
            """, (q, limit, offset)).fetchall()
            for row in rows:
                results.append({
                    "type": "image",
                    "document_id": row["document_id"],
                    "page_number": row["page_number"],
                    "file_path": row["file_path"],
                    "snippet": row["snippet"],
                    "rank": row["rank"],
                })
            count_row = conn.execute(
                "SELECT COUNT(*) FROM images_fts WHERE images_fts MATCH ?",
                (q,),
            ).fetchone()
            total += count_row[0]
        except Exception:
            pass

    conn.close()
    results.sort(key=lambda r: r.get("rank", 0))
    return {"total": total, "results": results[:limit]}
