"""Case CRUD routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from casestack.api.deps import get_app_state

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
    documents_dir: str


class ScanRequest(BaseModel):
    path: str


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
    conn.close()
    return cases


@router.post("/cases", status_code=201)
def create_case(body: CaseCreate):
    state = get_app_state()
    docs_dir = Path(body.documents_dir)
    if not docs_dir.is_dir():
        raise HTTPException(400, f"Directory not found: {body.documents_dir}")

    from casestack.api.deps import get_casestack_home
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
    }), encoding="utf-8")

    return state.register_case(
        slug=body.slug,
        name=body.name,
        description=body.description,
        case_yaml_path=str(case_yaml_path),
        output_dir=str(output_dir),
        documents_dir=str(docs_dir),
    )


@router.get("/cases/{slug}")
def get_case(slug: str):
    case = get_app_state().get_case(slug)
    if not case:
        raise HTTPException(404, "Case not found")
    return case


@router.delete("/cases/{slug}", status_code=204)
def delete_case(slug: str):
    state = get_app_state()
    if not state.get_case(slug):
        raise HTTPException(404, "Case not found")
    state.delete_case(slug)


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
