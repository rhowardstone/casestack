"""Unified search across all data types in a case."""
from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, HTTPException, Query

from casestack.api.deps import get_case_db

router = APIRouter()


# Backwards-compatible alias (in case anything imports this)
_get_case_db = get_case_db


def _sanitize_fts5(query: str) -> str:
    """Strip characters that cause FTS5 syntax errors."""
    cleaned = re.sub(r'[?!;:@#$%^&*()\[\]{}<>~/\\|`]', ' ', query)
    return re.sub(r'\s+', ' ', cleaned).strip()


@router.get("/cases/{slug}/search")
def search(slug: str, q: str = Query(...), type: str = Query("all"),
           offset: int = 0, limit: int = 50,
           date_from: str | None = Query(default=None, description="Filter docs on or after YYYY-MM-DD"),
           date_to: str | None = Query(default=None, description="Filter docs on or before YYYY-MM-DD")):
    """Unified search across pages, transcripts, images, entities."""
    db_path = _get_case_db(slug)
    q = _sanitize_fts5(q)
    if not q:
        return {"total": 0, "results": []}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    results = []
    total = 0
    requested_types = (
        {"pages", "transcripts", "images"}
        if type == "all"
        else set(type.split(","))
    )

    # Build optional date filter clause for documents join
    date_params: list = []
    date_where = ""
    if date_from:
        date_where += " AND d.date >= ?"
        date_params.append(date_from)
    if date_to:
        date_where += " AND d.date <= ?"
        date_params.append(date_to)

    # Search pages via FTS5
    if "pages" in requested_types:
        try:
            rows = conn.execute(f"""
                SELECT d.doc_id, d.title, d.date, p.page_number,
                       snippet(pages_fts, 0, '<mark>', '</mark>', '...', 64) as snippet,
                       rank
                FROM pages_fts
                JOIN pages p ON p.id = pages_fts.rowid
                JOIN documents d ON d.id = p.document_id
                WHERE pages_fts MATCH ?{date_where}
                ORDER BY rank
                LIMIT ? OFFSET ?
            """, (q, *date_params, limit, offset)).fetchall()
            for row in rows:
                results.append({
                    "type": "page",
                    "document_id": row["doc_id"],
                    "title": row["title"],
                    "date": row["date"],
                    "page_number": row["page_number"],
                    "snippet": row["snippet"],
                    "rank": row["rank"],
                })
            count_row = conn.execute(
                f"""SELECT COUNT(*) FROM pages_fts
                    JOIN pages p ON p.id = pages_fts.rowid
                    JOIN documents d ON d.id = p.document_id
                    WHERE pages_fts MATCH ?{date_where}""",
                (q, *date_params)
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
