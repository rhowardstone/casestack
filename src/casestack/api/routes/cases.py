"""Case CRUD routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from casestack.api.deps import get_app_state, get_casestack_home

router = APIRouter()

MEDIA_EXTENSIONS = {
    ".mp3", ".mp4", ".m4a", ".m4v", ".wav", ".flac", ".ogg", ".avi",
    ".mov", ".wmv", ".webm", ".mkv", ".vob", ".ts",
}
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".html", ".htm", ".json", ".xml"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp"}


class CaseCreate(BaseModel):
    name: str
    slug: str
    description: str = ""
    documents_dir: str = ""
    staging_session: str = ""  # if set, resolve documents_dir from staging


class ScanRequest(BaseModel):
    path: str


class ResolveDirectoryRequest(BaseModel):
    name: str
    files: list[dict]  # [{name: str, size: int}, ...]


@router.get("/cases")
def list_cases():
    state = get_app_state()
    cases = state.list_cases()
    # Enrich with ingest status
    conn = state._connect()
    for case in cases:
        slug = case["slug"]
        row = conn.execute(
            "SELECT status FROM ingest_runs WHERE case_slug = ? ORDER BY id DESC LIMIT 1",
            (slug,),
        ).fetchone()
        if row:
            case["ingest_status"] = row["status"]
        elif case.get("document_count", 0) > 0:
            case["ingest_status"] = "completed"
        else:
            case["ingest_status"] = "never_run"
        # Refresh entity_count from live DB when it's stale (0 but docs exist)
        if case.get("document_count", 0) > 0 and case.get("entity_count", 0) == 0:
            from casestack.api.deps import get_case_db
            import sqlite3 as _sqlite3
            try:
                db_path = get_case_db(slug)
                db = _sqlite3.connect(str(db_path))
                entity_count = db.execute(
                    "SELECT COUNT(DISTINCT lower(text) || entity_type) FROM extracted_entities"
                ).fetchone()[0]
                db.close()
                if entity_count > 0:
                    state.update_case_stats(slug, entity_count=entity_count)
                    case["entity_count"] = entity_count
            except Exception:
                pass
    conn.close()
    return cases


@router.post("/cases", status_code=201)
def create_case(body: CaseCreate):
    state = get_app_state()

    # Resolve documents_dir from staging session if provided
    if body.staging_session:
        staging_dir = get_casestack_home() / "staging" / body.staging_session
        if not staging_dir.is_dir():
            raise HTTPException(400, "Staging session not found")
        local_ref = staging_dir / ".local_ref"
        if local_ref.exists():
            docs_dir = Path(local_ref.read_text().strip())
        else:
            docs_dir = staging_dir
    elif body.documents_dir:
        docs_dir = Path(body.documents_dir)
    else:
        raise HTTPException(400, "Either documents_dir or staging_session required")

    if not docs_dir.is_dir():
        raise HTTPException(400, f"Directory not found: {docs_dir}")

    case_dir = get_casestack_home() / "cases" / body.slug
    case_dir.mkdir(parents=True, exist_ok=True)
    output_dir = case_dir / "output"
    output_dir.mkdir(exist_ok=True)
    case_yaml_path = case_dir / "case.yaml"

    import yaml
    case_yaml_path.write_text(yaml.dump({
        "name": body.name,
        "slug": body.slug,
        "description": body.description,
        "documents_dir": str(docs_dir),
        "output_dir": str(output_dir),
    }), encoding="utf-8")

    return state.register_case(
        slug=body.slug,
        name=body.name,
        description=body.description,
        case_yaml_path=str(case_yaml_path),
        output_dir=str(output_dir),
        documents_dir=str(docs_dir),
    )


@router.post("/cases/scan")
def scan_directory(body: ScanRequest):
    """Scan a directory and return file type counts."""
    docs_dir = Path(body.path)
    if not docs_dir.is_dir():
        raise HTTPException(400, f"Directory not found: {body.path}")

    counts = {"pdf": 0, "media": 0, "text": 0, "office": 0, "image": 0, "other": 0}
    for f in docs_dir.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext == ".pdf":
            counts["pdf"] += 1
        elif ext in MEDIA_EXTENSIONS:
            counts["media"] += 1
        elif ext in TEXT_EXTENSIONS:
            counts["text"] += 1
        elif ext in OFFICE_EXTENSIONS:
            counts["office"] += 1
        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"):
            counts["image"] += 1
        else:
            counts["other"] += 1
    counts["total"] = sum(counts.values())
    return counts


@router.post("/cases/resolve-directory")
def resolve_directory(body: ResolveDirectoryRequest):
    """Find absolute path of a directory by name + file listing.

    Used by the browser folder picker: the browser gives us the folder name
    and file listing but not the absolute path. Since browser and server share
    the same filesystem on localhost, we search common locations.
    """
    dir_name = body.name
    sample_files = {f["name"] for f in body.files[:20]}  # first 20 for matching

    # Search these locations for a directory matching the name + files
    home = Path.home()
    search_roots = [
        home,
        home / "Documents",
        home / "Desktop",
        home / "Downloads",
        Path.cwd(),
    ]
    # Also check common mount points on Linux/WSL
    for mnt in [Path("/mnt"), Path("/media"), Path("/home")]:
        if mnt.is_dir():
            search_roots.append(mnt)

    candidates = []
    seen = set()

    for root in search_roots:
        if not root.is_dir():
            continue
        # Search up to 3 levels deep for the directory name
        for depth_pattern in [dir_name, f"*/{dir_name}", f"*/*/{dir_name}"]:
            for candidate in root.glob(depth_pattern):
                real = candidate.resolve()
                if real in seen or not real.is_dir():
                    continue
                seen.add(real)
                # Verify by checking if sample files exist
                if sample_files:
                    found = {f.name for f in real.iterdir() if f.is_file()}
                    overlap = sample_files & found
                    if len(overlap) >= min(3, len(sample_files)):
                        candidates.append(str(real))
                else:
                    candidates.append(str(real))

    if len(candidates) == 1:
        return {"path": candidates[0], "status": "found"}
    elif len(candidates) > 1:
        return {"paths": candidates, "status": "multiple"}
    else:
        return {"status": "not_found"}


# Parameterized routes MUST come after literal routes to avoid matching conflicts
@router.get("/cases/{slug}")
def get_case(slug: str):
    state = get_app_state()
    case = state.get_case(slug)
    if not case:
        raise HTTPException(404, "Case not found")

    # If counts are stale/missing, try to read live stats from the output DB.
    # This handles cases ingested via CLI where update_case_stats was never called,
    # or where entity extraction happened after the initial stats write.
    if case.get("document_count", 0) == 0 or case.get("entity_count", 0) == 0:
        from casestack.api.deps import get_case_db
        import sqlite3 as _sqlite3
        try:
            db_path = get_case_db(slug)
            db = _sqlite3.connect(str(db_path))
            doc_count = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            page_count = db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            try:
                img_count = db.execute("SELECT COUNT(*) FROM extracted_images").fetchone()[0]
            except _sqlite3.OperationalError:
                img_count = 0
            try:
                trans_count = db.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
            except _sqlite3.OperationalError:
                trans_count = 0
            try:
                entity_count = db.execute("SELECT COUNT(DISTINCT lower(text) || entity_type) FROM extracted_entities").fetchone()[0]
            except _sqlite3.OperationalError:
                entity_count = 0
            db.close()
            if doc_count > 0:
                state.update_case_stats(
                    slug,
                    document_count=doc_count,
                    page_count=page_count,
                    image_count=img_count,
                    transcript_count=trans_count,
                    entity_count=entity_count,
                    db_size_bytes=db_path.stat().st_size,
                )
                case.update({
                    "document_count": doc_count,
                    "page_count": page_count,
                    "image_count": img_count,
                    "transcript_count": trans_count,
                    "entity_count": entity_count,
                    "db_size_bytes": db_path.stat().st_size,
                })
        except HTTPException:
            pass  # DB not found — counts stay 0

    return case


@router.get("/cases/{slug}/stats")
def get_case_stats(slug: str):
    """Return timeline and top-entity stats for the dashboard."""
    import sqlite3 as _sqlite3
    from casestack.api.deps import get_case_db
    db_path = get_case_db(slug)
    conn = _sqlite3.connect(str(db_path))
    try:
        # Date range
        row = conn.execute(
            "SELECT MIN(date), MAX(date) FROM documents WHERE date IS NOT NULL"
        ).fetchone()
        date_min, date_max = row if row else (None, None)

        # Docs by year
        year_rows = conn.execute(
            """SELECT substr(date,1,4) AS yr, COUNT(*) AS cnt
               FROM documents WHERE date IS NOT NULL AND length(date) >= 4
               GROUP BY yr ORDER BY yr"""
        ).fetchall()
        docs_by_year = [{"year": r[0], "count": r[1]} for r in year_rows]

        # Top entities (persons only, noise-filtered)
        try:
            noise_filter = (
                "length(trim(text)) > 2 "
                "AND INSTR(text, char(13)) = 0 "
                "AND INSTR(text, char(10)) = 0 "
                "AND text NOT GLOB '*>*' "
                "AND text NOT GLOB '*<*' "
                "AND text NOT GLOB '*@*' "
                "AND INSTR(text, '](') = 0 "
                "AND lower(text) NOT IN ("
                "  'tel','fax','subject','from','to','cc','bcc','re','fw','fwd',"
                "  'esq','mr','mrs','ms','dr','prof','sir','hon',"
                "  'via','attn','date','p.s.','ps','nb','n.b.',"
                "  'inc','llc','ltd','corp','co','llp','html',"
                "  'stock quotes','market data and analysis','global business and financial news',"
                "  'digital products','real-time','real time','xa9','breaking news',"
                "  'morning squawk','nj 07632 data','the daily news e-edition',"
                "  'twitter','facebook','instagram','linkedin','youtube',"
                "  'jeffrey','peter','john','david','james','michael','robert','tom','bob',"
                "  'william','richard','thomas','charles','george','mark','paul','joe',"
                "  'andrew','chris','eric','adam','alan','alex','brian','jason','bill',"
                "  'kevin','ryan','scott','steven','timothy','virginia','sarah','biden',"
                "  'jack','jim','frank','henry','ted','ned','sam','dan','tim','rob','jim',"
                "  'covid','covid-19','coronavirus','omicron','delta','alpha','beta'"
                ") "
                "AND text NOT GLOB '*[0-9]*[0-9]*[0-9]*'"
            )
            # Prioritise persons (top 8) then fill remainder with orgs/places.
            # Cross-type dedup: exclude PERSONs dominated by GPE (misclassified places).
            # Eponymous-org names (Trump, Bloomberg) are kept — only places (GPE) are filtered.
            person_rows = conn.execute(
                f"""WITH pc AS (
                      SELECT text, lower(text) AS ltext, COUNT(DISTINCT document_id) AS cnt
                      FROM extracted_entities
                      WHERE entity_type = 'PERSON' AND {noise_filter}
                        AND text NOT GLOB '* Ave'  AND text NOT GLOB '* St'
                        AND text NOT GLOB '* Blvd' AND text NOT GLOB '* Rd'
                        AND text NOT GLOB '* Dr'   AND text NOT GLOB '* Lane'
                        AND text NOT GLOB '* Way'  AND text NOT GLOB '* Pkwy'
                        AND lower(text) NOT IN ('hackettstown','view','nj','ny','ca','tx','fl','shipped','delivered','pending','processing')
                        AND trim(text) GLOB '*[a-z]*'
                      GROUP BY lower(text)
                    ),
                    gc AS (
                      SELECT lower(text) AS ltext, COUNT(DISTINCT document_id) AS gpe_cnt
                      FROM extracted_entities WHERE entity_type = 'GPE'
                      GROUP BY lower(text)
                    )
                    SELECT pc.text, 'PERSON' AS entity_type, pc.cnt
                    FROM pc
                    LEFT JOIN gc ON pc.ltext = gc.ltext
                    WHERE gc.gpe_cnt IS NULL OR pc.cnt > gc.gpe_cnt
                    ORDER BY pc.cnt DESC
                    LIMIT 12"""
            ).fetchall()
            # Deduplicate name variants: if every word in name A appears in name B
            # (e.g. "Trump" ⊆ "Donald Trump"), keep only the highest-count entry.
            deduped = []
            for row in person_rows:
                words = set(row[0].lower().split())
                dominated = any(
                    words.issubset(set(kept[0].lower().split()))
                    or set(kept[0].lower().split()).issubset(words)
                    for kept in deduped
                )
                if not dominated:
                    deduped.append(row)
            person_rows = deduped[:8]
            org_rows = conn.execute(
                f"""SELECT text, entity_type, COUNT(DISTINCT document_id) AS cnt
                    FROM extracted_entities
                    WHERE entity_type IN ('ORG','GPE') AND {noise_filter}
                    GROUP BY lower(text)
                    ORDER BY cnt DESC
                    LIMIT 4"""
            ).fetchall()
            entity_rows = list(person_rows) + list(org_rows)
            top_entities = [{"name": r[0], "type": r[1], "count": r[2]} for r in entity_rows]
        except _sqlite3.OperationalError:
            top_entities = []

        return {
            "date_min": date_min,
            "date_max": date_max,
            "docs_by_year": docs_by_year,
            "top_entities": top_entities,
        }
    finally:
        conn.close()


class UpdateCaseBody(BaseModel):
    name: str | None = None
    description: str | None = None


@router.put("/cases/{slug}")
def update_case(slug: str, body: UpdateCaseBody):
    state = get_app_state()
    case = state.get_case(slug)
    if not case:
        raise HTTPException(404, "Case not found")
    conn = state._connect()
    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if updates:
        sets = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(f"UPDATE cases SET {sets} WHERE slug = ?",
                     (*updates.values(), slug))
        conn.commit()
    conn.close()
    return state.get_case(slug)


@router.delete("/cases/{slug}", status_code=204)
def delete_case(slug: str):
    state = get_app_state()
    if not state.get_case(slug):
        raise HTTPException(404, "Case not found")
    state.delete_case(slug)
