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
    limit: int | None = None,
):
    """List persons/entities in the case database.

    Prefers the ``persons`` registry table when populated.
    Falls back to the ``extracted_entities`` table (auto-NER output),
    returning deduplicated entity mentions grouped by (text, entity_type).
    """
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Check if registry-based persons exist
        person_count = conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
        if person_count > 0:
            if category and limit is not None:
                rows = conn.execute(
                    "SELECT * FROM persons WHERE category = ? ORDER BY name LIMIT ? OFFSET ?",
                    (category, limit, offset),
                ).fetchall()
            elif category:
                rows = conn.execute(
                    "SELECT * FROM persons WHERE category = ? ORDER BY name",
                    (category,),
                ).fetchall()
            elif limit is not None:
                rows = conn.execute(
                    "SELECT * FROM persons ORDER BY name LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM persons ORDER BY name").fetchall()
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "type": r["category"],
                    "mentions": 0,
                    "aliases": r["aliases"],
                    "short_bio": r["short_bio"],
                }
                for r in rows
            ]

        # Fallback: aggregate extracted_entities (auto-NER)
        # Noise filter: exclude OCR artifacts, CSS fragments, numeric/symbol tokens.
        noise_clause = (
            "length(trim(text)) > 2 "
            "AND lower(text) != 'nan' "
            "AND lower(text) != 'null' "
            "AND lower(text) NOT IN ('tel','fax','subject','from','to','cc','bcc','date','re','fw','fwd','via','attn',"
            "  'html','llc','ltd','corp','inc','co','llp','esq','mr','mrs','ms','dr','prof','sir','hon',"
            "  'update profile/email address','unsubscribe','privacy policy','read more','view online',"
            "  'sent from my iphone','sent from my ipad','click here','see more',"
            "  'stock quotes','market data and analysis','global business and financial news',"
            "  'digital products','real-time','real time','xa9','breaking news',"
            "  'morning squawk','nj 07632 data','the daily news e-edition',"
            "  'twitter','facebook','instagram','linkedin','youtube',"
            "  'jeffrey','peter','john','david','james','michael','robert','tom','bob',"
            "  'william','richard','thomas','charles','george','mark','paul','joe','bill',"
            "  'andrew','chris','eric','adam','alan','alex','brian','jason','virginia',"
            "  'kevin','ryan','scott','steven','timothy','sarah','biden',"
            "  'jack','jim','frank','henry','ted','ned','sam','dan','tim','rob',"
            "  'covid','covid-19','coronavirus','omicron','delta','alpha','beta',"
            "  'view','hackettstown','nj','ny','ca','tx','fl') "
            "AND text NOT GLOB '* Ave' "   # address suffixes
            "AND text NOT GLOB '* St' "
            "AND text NOT GLOB '* Blvd' "
            "AND text NOT GLOB '* Rd' "
            "AND text NOT GLOB '* Dr' "
            "AND text NOT GLOB '* Lane' "
            "AND text NOT GLOB '* Way' "
            "AND text NOT GLOB '* Pkwy' "
            "AND text NOT GLOB '*{*' "   # CSS/HTML fragments
            "AND text NOT GLOB '*}*' "
            "AND text NOT GLOB '*<*' "
            "AND text NOT GLOB '*>*' "   # email quote markers
            "AND text NOT GLOB '*•*' "   # redaction bullet artifacts
            "AND text NOT GLOB '*▪*' "
            "AND text NOT GLOB '*■*' "
            "AND text NOT GLOB '*✓*' "
            "AND text NOT GLOB '*♦*' "
            "AND text NOT GLOB '*≥*' "
            "AND text NOT GLOB '*[*]*' " # glob wildcards / markdown
            "AND text NOT GLOB '*@*' "   # email addresses
            "AND INSTR(text, '](') = 0 " # markdown link fragments like "text](url"
            "AND text NOT GLOB '*[0-9]px' "  # CSS pixel values
            "AND text NOT GLOB '*[0-9]em' "  # CSS em values
            "AND text NOT GLOB '*[0-9]%' "   # CSS percentage values
            "AND INSTR(text, char(13)) = 0 "  # no carriage return (\r)
            "AND INSTR(text, char(10)) = 0 "  # no newline (\n)
            "AND NOT (text GLOB '[0-9]*' AND length(trim(text)) < 4) "  # pure numbers < 4 chars
            "AND trim(text) GLOB '*[A-Za-z]*' "  # must contain at least one letter
        )
        type_filter = f"WHERE {noise_clause}"
        params: list = []
        if category:
            type_filter += " AND upper(entity_type) = upper(?)"
            params.append(category)
        else:
            # Default: exclude high-noise NLP types (temporal, numeric, etc.)
            type_filter += (
                " AND entity_type NOT IN "
                "('DATE','TIME','CARDINAL','ORDINAL','PERCENT','MONEY','QUANTITY','LANGUAGE')"
            )
        if limit is not None:
            params.extend([limit, offset])
            rows = conn.execute(
                f"""SELECT entity_type,
                           text,
                           COUNT(DISTINCT document_id) AS mentions,
                           lower(text) AS id
                    FROM extracted_entities
                    {type_filter}
                    GROUP BY lower(text)
                    ORDER BY mentions DESC
                    LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
        else:
            rows = conn.execute(
                f"""SELECT entity_type,
                           text,
                           COUNT(DISTINCT document_id) AS mentions,
                           lower(text) AS id
                    FROM extracted_entities
                    {type_filter}
                    GROUP BY lower(text)
                    ORDER BY mentions DESC""",
                params,
            ).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["text"],
                "type": r["entity_type"].upper(),
                "mentions": r["mentions"],
            }
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/cases/{slug}/entities/graph")
def entity_graph(slug: str, limit: int = 200):
    """Return entity co-occurrence graph data for d3-force visualization.

    Prefers registry-based persons when available. Falls back to auto-NER
    extracted_entities (PERSON + ORG types), building co-occurrence edges from
    entities that appear in the same document.
    Must be declared before the ``/{person_id}`` route so FastAPI matches it first.
    """
    db_path = get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        person_count = conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0]

        if person_count > 0:
            # Registry-based graph (original logic)
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
                    "type": r["category"],
                    "mentions": r["doc_count"],
                }
                for r in persons
            ]
            node_ids = {r["id"] for r in persons}

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
                pass
            return {"nodes": nodes, "edges": edges}

        # Auto-NER graph from extracted_entities
        # Nodes: top PERSON + ORG entities by mention count
        node_rows = conn.execute(
            """SELECT entity_type || ':' || lower(text) AS id,
                      text AS name,
                      entity_type AS category,
                      COUNT(DISTINCT document_id) AS doc_count
               FROM extracted_entities
               WHERE entity_type IN ('PERSON', 'ORG')
                 AND length(trim(text)) > 2
                 AND lower(text) != 'nan'
                 AND lower(text) != 'null'
                 AND text NOT GLOB '*{*'
                 AND text NOT GLOB '*}*'
                 AND text NOT GLOB '*<*'
                 AND text NOT GLOB '*>*'
                 AND text NOT GLOB '*/*'
                 AND text NOT GLOB '*[*]*'
                 AND text NOT GLOB '*@*'
                 AND text NOT GLOB '*http*'
                 AND text NOT GLOB '*=*'
                 AND text NOT GLOB '*;*'
                 AND text NOT GLOB '*[0-9]px'
                 AND text NOT GLOB '*[0-9]em'
                 AND text NOT GLOB '*[0-9]%'
                 AND INSTR(text, char(13)) = 0
                 AND INSTR(text, char(10)) = 0
                 AND lower(text) NOT IN (
                   'tel','fax','subject','from','to','cc','bcc','date','re','fw','fwd','via','attn',
                   'html','llc','ltd','corp','inc','co','llp','esq','mr','mrs','ms','dr','prof','sir','hon',
                   'stock quotes','market data and analysis','global business and financial news',
                   'digital products','real-time','real time','xa9','breaking news',
                   'morning squawk','nj 07632 data','the daily news e-edition',
                   'twitter','facebook','instagram','linkedin','youtube',
                   'jeffrey','peter','john','david','james','michael','robert','tom','bob',
                   'william','richard','thomas','charles','george','mark','paul','joe','bill',
                   'andrew','chris','eric','adam','alan','alex','brian','jason','virginia',
                   'kevin','ryan','scott','steven','timothy','sarah','biden',
                   'jack','jim','frank','henry','ted','ned','sam','dan','tim','rob',
                   'covid','covid-19','coronavirus','omicron','delta','alpha','beta',
                   'view','hackettstown','nj','ny','ca','tx','fl',
                   'shipped','delivered','pending','processing',
                   'shipment total','help department','critical','floor'
                 )
                 AND text NOT GLOB '* Ave' AND text NOT GLOB '* St'
                 AND text NOT GLOB '* Blvd' AND text NOT GLOB '* Rd'
                 AND text NOT GLOB '* N.' AND text NOT GLOB '* S.'
                 AND trim(text) GLOB '*[a-z]*'
                 AND NOT (text GLOB '[0-9]*' AND length(trim(text)) < 5)
                 AND length(trim(text)) >= 3
               GROUP BY entity_type, lower(text)
               HAVING COUNT(*) >= 5
               ORDER BY doc_count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        nodes = [
            {
                "id": r["id"],
                "name": r["name"],
                "type": r["category"].lower(),
                "mentions": r["doc_count"],
            }
            for r in node_rows
        ]
        node_id_set = {r["id"] for r in nodes}

        # Edges: co-occurrence within same document
        edges = []
        try:
            edge_rows = conn.execute(
                """SELECT
                       a.entity_type || ':' || lower(a.text) AS source,
                       b.entity_type || ':' || lower(b.text) AS target,
                       COUNT(*) AS weight
                   FROM extracted_entities a
                   JOIN extracted_entities b
                     ON a.document_id = b.document_id
                    AND a.entity_type IN ('PERSON', 'ORG')
                    AND b.entity_type IN ('PERSON', 'ORG')
                    AND (a.entity_type || ':' || lower(a.text))
                        < (b.entity_type || ':' || lower(b.text))
                    AND length(trim(a.text)) >= 3
                    AND length(trim(b.text)) >= 3
                    AND a.text NOT GLOB '*{*' AND a.text NOT GLOB '*}*'
                    AND a.text NOT GLOB '*<*' AND a.text NOT GLOB '*>*'
                    AND a.text NOT GLOB '*/*' AND a.text NOT GLOB '*@*'
                    AND a.text NOT GLOB '*http*' AND a.text NOT GLOB '*=*'
                    AND b.text NOT GLOB '*{*' AND b.text NOT GLOB '*}*'
                    AND b.text NOT GLOB '*<*' AND b.text NOT GLOB '*>*'
                    AND b.text NOT GLOB '*/*' AND b.text NOT GLOB '*@*'
                    AND b.text NOT GLOB '*http*' AND b.text NOT GLOB '*=*'
                   GROUP BY source, target
                   HAVING weight >= 3
                   ORDER BY weight DESC
                   LIMIT 400"""
            ).fetchall()
            edges = [
                {"source": r["source"], "target": r["target"], "weight": r["weight"]}
                for r in edge_rows
                if r["source"] in node_id_set and r["target"] in node_id_set
            ]
        except Exception:
            pass

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
