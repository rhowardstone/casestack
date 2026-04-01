"""Projects API routes — investigation boards that aggregate multiple datasets."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from casestack.api.deps import get_app_state, get_case_db

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str
    slug: str
    description: str = ""
    dataset_slugs: list[str] = []  # datasets to link immediately


class DatasetLink(BaseModel):
    dataset_slug: str


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("/projects")
def list_projects():
    state = get_app_state()
    projects = state.list_projects()
    for proj in projects:
        datasets = state.get_project_datasets(proj["slug"])
        proj["dataset_count"] = len(datasets)
        proj["datasets"] = [{"slug": d["slug"], "name": d["name"]} for d in datasets]
        proj["total_documents"] = sum(d.get("document_count", 0) for d in datasets)
    return projects


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate):
    state = get_app_state()
    # Validate dataset slugs exist
    for ds in body.dataset_slugs:
        if not state.get_case(ds):
            raise HTTPException(400, f"Dataset not found: {ds}")
    project = state.create_project(
        slug=body.slug, name=body.name, description=body.description
    )
    for ds in body.dataset_slugs:
        state.add_dataset_to_project(body.slug, ds)
    project["datasets"] = body.dataset_slugs
    return project


@router.get("/projects/{slug}")
def get_project(slug: str):
    state = get_app_state()
    project = state.get_project(slug)
    if not project:
        raise HTTPException(404, "Project not found")
    state.touch_project(slug)
    datasets = state.get_project_datasets(slug)
    project["datasets"] = datasets
    project["total_documents"] = sum(d.get("document_count", 0) for d in datasets)
    return project


@router.delete("/projects/{slug}", status_code=204)
def delete_project(slug: str):
    state = get_app_state()
    if not state.get_project(slug):
        raise HTTPException(404, "Project not found")
    state.delete_project(slug)


# ---------------------------------------------------------------------------
# Dataset linking
# ---------------------------------------------------------------------------

@router.post("/projects/{slug}/datasets", status_code=201)
def link_dataset(slug: str, body: DatasetLink):
    state = get_app_state()
    if not state.get_project(slug):
        raise HTTPException(404, "Project not found")
    if not state.get_case(body.dataset_slug):
        raise HTTPException(404, f"Dataset not found: {body.dataset_slug}")
    state.add_dataset_to_project(slug, body.dataset_slug)
    return {"project": slug, "dataset": body.dataset_slug, "status": "linked"}


@router.delete("/projects/{slug}/datasets/{dataset_slug}", status_code=204)
def unlink_dataset(slug: str, dataset_slug: str):
    state = get_app_state()
    if not state.get_project(slug):
        raise HTTPException(404, "Project not found")
    state.remove_dataset_from_project(slug, dataset_slug)


# ---------------------------------------------------------------------------
# Federated stats — merge timeline + entities across all datasets
# ---------------------------------------------------------------------------

@router.get("/projects/{slug}/stats")
def project_stats(slug: str):
    state = get_app_state()
    if not state.get_project(slug):
        raise HTTPException(404, "Project not found")

    datasets = state.get_project_datasets(slug)
    if not datasets:
        return {"date_min": None, "date_max": None, "docs_by_year": [], "top_entities": [], "datasets": []}

    all_years: dict[int, int] = {}
    entity_counts: dict[tuple, int] = {}
    date_min: str | None = None
    date_max: str | None = None
    dataset_summaries = []

    for ds in datasets:
        try:
            db_path = get_case_db(ds["slug"])
        except HTTPException:
            continue

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Timeline
        rows = conn.execute(
            "SELECT strftime('%Y', date) AS yr, COUNT(*) AS cnt FROM documents "
            "WHERE date IS NOT NULL AND date != '' GROUP BY yr"
        ).fetchall()
        for r in rows:
            if r["yr"]:
                all_years[int(r["yr"])] = all_years.get(int(r["yr"]), 0) + r["cnt"]

        # Date range
        r = conn.execute(
            "SELECT MIN(date) AS mn, MAX(date) AS mx FROM documents WHERE date IS NOT NULL AND date != ''"
        ).fetchone()
        if r and r["mn"]:
            if date_min is None or r["mn"] < date_min:
                date_min = r["mn"]
            if date_max is None or r["mx"] > date_max:
                date_max = r["mx"]

        # Entities
        ent_rows = conn.execute(
            """SELECT entity_type, text, COUNT(DISTINCT document_id) AS doc_count
               FROM extracted_entities
               WHERE length(text) > 1
                 AND length(text) < 60
                 AND lower(text) NOT IN (
                   'tel','fax','subject','from','to','cc','bcc','re','fw','fwd',
                   'esq','mr','mrs','ms','dr','prof','sir','hon',
                   'via','attn','date','p.s.','ps','nb','n.b.',
                   'inc','llc','ltd','corp','co','llp'
                 )
                 AND text NOT GLOB '*[0-9]*[0-9]*[0-9]*'
               GROUP BY entity_type, lower(text)
               ORDER BY doc_count DESC
               LIMIT 100"""
        ).fetchall()
        for r in ent_rows:
            key = (r["entity_type"], r["text"].strip())
            entity_counts[key] = entity_counts.get(key, 0) + r["doc_count"]

        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        conn.close()

        dataset_summaries.append({
            "slug": ds["slug"],
            "name": ds["name"],
            "document_count": doc_count,
        })

    docs_by_year = sorted(
        [{"year": yr, "count": cnt} for yr, cnt in all_years.items()],
        key=lambda x: x["year"],
    )

    top_entities = sorted(
        [{"type": k[0], "name": k[1], "doc_count": v} for k, v in entity_counts.items()],
        key=lambda x: x["doc_count"],
        reverse=True,
    )[:30]

    return {
        "date_min": date_min,
        "date_max": date_max,
        "docs_by_year": docs_by_year,
        "top_entities": top_entities,
        "datasets": dataset_summaries,
    }


# ---------------------------------------------------------------------------
# Federated search across all datasets in a project
# ---------------------------------------------------------------------------

@router.get("/projects/{slug}/search")
def project_search(slug: str, q: str = "", limit: int = 20):
    state = get_app_state()
    if not state.get_project(slug):
        raise HTTPException(404, "Project not found")
    if not q.strip():
        return []

    datasets = state.get_project_datasets(slug)
    results = []

    for ds in datasets:
        try:
            db_path = get_case_db(ds["slug"])
        except HTTPException:
            continue

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        try:
            rows = conn.execute(
                """SELECT d.doc_id, d.title, d.date, d.summary,
                          snippet(pages_fts, 0, '<mark>', '</mark>', '...', 32) AS snippet
                   FROM pages_fts
                   JOIN pages p ON p.rowid = pages_fts.rowid
                   JOIN documents d ON d.doc_id = p.doc_id
                   WHERE pages_fts MATCH ?
                   LIMIT ?""",
                (q, limit // len(datasets) + 5),
            ).fetchall()
            for r in rows:
                results.append({**dict(r), "dataset_slug": ds["slug"], "dataset_name": ds["name"]})
        except Exception:
            pass
        conn.close()

    # Sort by relevance proxy (title match first)
    q_lower = q.lower()
    results.sort(key=lambda x: 0 if q_lower in (x.get("title") or "").lower() else 1)
    return results[:limit]
