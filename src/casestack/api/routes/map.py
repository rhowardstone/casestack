"""Geographic data route for choropleth / heatmap visualization."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter

from casestack.api.deps import get_case_db

router = APIRouter()


@router.get("/cases/{slug}/map")
def get_map_data(slug: str):
    """Return location entity mentions for geographic visualization.

    Pulls from the ``extracted_entities`` table filtering on location-type
    entities (GPE, LOC, LOCATION), aggregated by entity text.
    """
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT text AS location, COUNT(*) AS mentions
               FROM extracted_entities
               WHERE entity_type IN ('GPE', 'LOC', 'LOCATION')
               GROUP BY text
               ORDER BY mentions DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()
