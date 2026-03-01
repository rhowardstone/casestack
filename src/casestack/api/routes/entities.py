"""Entity (person) listing and graph routes."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query

from casestack.api.deps import get_case_db

router = APIRouter()


@router.get("/cases/{slug}/entities")
def list_entities(
    slug: str,
    category: str | None = None,
    offset: int = 0,
    limit: int = 100,
):
    """List persons/entities in the case database.

    The ``persons`` table uses a ``category`` column (not ``type``).
    Optionally filter by category.
    """
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if category:
            rows = conn.execute(
                "SELECT * FROM persons WHERE category = ? ORDER BY name LIMIT ? OFFSET ?",
                (category, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM persons ORDER BY name LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/cases/{slug}/entities/graph")
def entity_graph(slug: str, limit: int = 200):
    """Return entity co-occurrence graph data for d3-force visualization.

    Nodes are persons; edges connect persons that appear in the same document.
    Must be declared before the ``/{person_id}`` route so FastAPI matches it first.
    """
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Get persons that have at least one document link
        persons = conn.execute(
            """SELECT p.*, COUNT(dp.document_id) as doc_count
               FROM persons p
               JOIN document_persons dp ON dp.person_id = p.id
               GROUP BY p.id
               ORDER BY doc_count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        nodes = [
            {
                "id": r["id"],
                "name": r["name"],
                "category": r["category"],
                "doc_count": r["doc_count"],
            }
            for r in persons
        ]
        node_ids = {r["id"] for r in persons}

        # Edges: persons co-occurring in the same document
        edges = []
        try:
            edge_rows = conn.execute(
                """SELECT dp1.person_id as source, dp2.person_id as target,
                          COUNT(*) as weight
                   FROM document_persons dp1
                   JOIN document_persons dp2
                     ON dp1.document_id = dp2.document_id
                    AND dp1.person_id < dp2.person_id
                   GROUP BY dp1.person_id, dp2.person_id
                   ORDER BY weight DESC
                   LIMIT 500"""
            ).fetchall()
            edges = [
                {"source": r["source"], "target": r["target"], "weight": r["weight"]}
                for r in edge_rows
                if r["source"] in node_ids and r["target"] in node_ids
            ]
        except Exception:
            pass  # table may be empty

        return {"nodes": nodes, "edges": edges}
    finally:
        conn.close()


@router.get("/cases/{slug}/entities/{person_id}")
def get_entity(slug: str, person_id: str):
    """Get a single person/entity by id, including linked documents."""
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM persons WHERE id = ?", (person_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Entity not found")

        # Fetch linked document ids
        doc_rows = conn.execute(
            "SELECT document_id FROM document_persons WHERE person_id = ?",
            (person_id,),
        ).fetchall()
        result = dict(row)
        result["document_ids"] = [r["document_id"] for r in doc_rows]
        return result
    finally:
        conn.close()
