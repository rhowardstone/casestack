"""Ingest start/stop/status routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from casestack.api.deps import get_app_state

router = APIRouter()

# In-memory tracking of running ingest (v1: single ingest at a time)
_running_ingest: dict = {}


class IngestStartRequest(BaseModel):
    pipeline_overrides: dict[str, bool] | None = None


@router.post("/cases/{slug}/ingest/start")
def start_ingest(slug: str, body: IngestStartRequest | None = None):
    """Start the ingest pipeline for a case."""
    state = get_app_state()
    case_info = state.get_case(slug)
    if not case_info:
        raise HTTPException(404, "Case not found")

    if slug in _running_ingest and _running_ingest[slug].get("status") == "running":
        raise HTTPException(409, "Ingest already running for this case")

    from casestack.case import CaseConfig
    from pathlib import Path
    import threading
    from datetime import datetime, timezone

    case_yaml = Path(case_info["case_yaml_path"])
    case = CaseConfig.from_yaml(case_yaml)

    overrides = {}
    if body and body.pipeline_overrides:
        overrides = body.pipeline_overrides

    now = datetime.now(timezone.utc).isoformat()
    conn = state._connect()
    cursor = conn.execute(
        "INSERT INTO ingest_runs (case_slug, started_at, status) VALUES (?, ?, 'running')",
        (slug, now),
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()

    def _run():
        from casestack.ingest import run_ingest
        from casestack.api.websocket import WebSocketCallback
        import sqlite3
        cb = WebSocketCallback(slug)
        try:
            db_path = run_ingest(case, skip_overrides=overrides or None, callback=cb)

            # Update case stats from the output database
            if db_path and db_path.exists():
                case_db = sqlite3.connect(str(db_path))
                doc_count = case_db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                page_count = case_db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
                try:
                    img_count = case_db.execute("SELECT COUNT(*) FROM extracted_images").fetchone()[0]
                except sqlite3.OperationalError:
                    img_count = 0
                try:
                    trans_count = case_db.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
                except sqlite3.OperationalError:
                    trans_count = 0
                try:
                    entity_count = case_db.execute(
                        "SELECT COUNT(DISTINCT lower(text) || entity_type) FROM extracted_entities"
                    ).fetchone()[0]
                except sqlite3.OperationalError:
                    entity_count = 0
                case_db.close()
                state.update_case_stats(
                    slug,
                    document_count=doc_count,
                    page_count=page_count,
                    image_count=img_count,
                    transcript_count=trans_count,
                    entity_count=entity_count,
                    db_size_bytes=db_path.stat().st_size,
                )

            conn = state._connect()
            conn.execute(
                "UPDATE ingest_runs SET status='completed', completed_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), run_id),
            )
            conn.commit()
            conn.close()
            _running_ingest[slug]["status"] = "completed"
        except Exception as exc:
            cb.on_error("", str(exc))
            conn = state._connect()
            conn.execute(
                "UPDATE ingest_runs SET status='failed', error_message=?, completed_at=? WHERE id=?",
                (str(exc), datetime.now(timezone.utc).isoformat(), run_id),
            )
            conn.commit()
            conn.close()
            _running_ingest[slug]["status"] = "failed"
            _running_ingest[slug]["error_message"] = str(exc)

    thread = threading.Thread(target=_run, daemon=True)
    _running_ingest[slug] = {"thread": thread, "status": "running", "run_id": run_id}
    thread.start()

    return {"status": "started", "run_id": run_id}


@router.get("/cases/{slug}/ingest/status")
def ingest_status(slug: str):
    """Get current ingest status."""
    if slug in _running_ingest:
        result = {
            "status": _running_ingest[slug]["status"],
            "run_id": _running_ingest[slug].get("run_id"),
        }
        if _running_ingest[slug].get("error_message"):
            result["error_message"] = _running_ingest[slug]["error_message"]
        return result
    state = get_app_state()
    conn = state._connect()
    row = conn.execute(
        "SELECT * FROM ingest_runs WHERE case_slug = ? ORDER BY id DESC LIMIT 1",
        (slug,),
    ).fetchone()
    conn.close()

    if row:
        return dict(row)

    # Check if case has existing output (e.g. ingested via CLI)
    case_info = state.get_case(slug)
    if case_info:
        # Check stored count first (fast path)
        if case_info.get("document_count", 0) > 0:
            return {"status": "completed", "source": "cli"}
        # Otherwise probe the output DB directly (handles CLI-ingested cases where
        # update_case_stats was never called)
        from casestack.api.deps import get_case_db
        import sqlite3 as _sqlite3
        try:
            db_path = get_case_db(slug)
            db = _sqlite3.connect(str(db_path))
            doc_count = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            db.close()
            if doc_count > 0:
                return {"status": "completed", "source": "cli"}
        except Exception:
            pass

    return {"status": "never_run"}


_reembed_status: dict[str, dict] = {}
_dc_fetch_status: dict[str, dict] = {}


class DocumentCloudFetchRequest(BaseModel):
    project_url: str  # DC project URL, slug, or numeric ID
    fetch_annotations: bool = False
    max_docs: int | None = None  # limit for testing; None = all


@router.post("/cases/{slug}/documentcloud/fetch")
def fetch_documentcloud(slug: str, body: DocumentCloudFetchRequest):
    """Download PDFs from a DocumentCloud project into the case documents_dir.

    Runs in the background.  Check status with
    GET /cases/{slug}/documentcloud/fetch/status.

    The downloaded PDFs are placed in the case's documents_dir; run
    POST /cases/{slug}/ingest/start afterwards to index them.
    """
    import threading
    from casestack.api.deps import get_app_state

    state = get_app_state()
    case_info = state.get_case(slug)
    if not case_info:
        raise HTTPException(404, "Case not found")

    if _dc_fetch_status.get(slug, {}).get("status") == "running":
        raise HTTPException(409, "DocumentCloud fetch already running for this case")

    from pathlib import Path as _Path
    from casestack.case import CaseConfig as _CaseConfig

    case = _CaseConfig.from_yaml(_Path(case_info["case_yaml_path"]))

    def _run():
        _dc_fetch_status[slug] = {"status": "running"}
        try:
            from casestack.processors.documentcloud_fetcher import DocumentCloudFetcher
            fetcher = DocumentCloudFetcher()
            results = fetcher.fetch_project(
                body.project_url,
                case.documents_dir,
                fetch_annotations=body.fetch_annotations,
                max_docs=body.max_docs,
            )
            downloaded = sum(1 for r in results if r["status"] == "downloaded")
            skipped = sum(1 for r in results if r["status"] == "skipped")
            failed = sum(1 for r in results if r["status"] == "failed")
            _dc_fetch_status[slug] = {
                "status": "completed",
                "downloaded": downloaded,
                "skipped": skipped,
                "failed": failed,
                "total": len(results),
            }
        except Exception as exc:
            _dc_fetch_status[slug] = {"status": "failed", "error": str(exc)}

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "project_url": body.project_url}


@router.get("/cases/{slug}/documentcloud/fetch/status")
def documentcloud_fetch_status(slug: str):
    """Get DocumentCloud fetch status."""
    return _dc_fetch_status.get(slug, {"status": "never_run"})


@router.post("/cases/{slug}/reembed")
def start_reembed(slug: str):
    """Generate page-level vector embeddings for semantic search.

    Runs in the background.  Check status with GET /cases/{slug}/reembed/status.
    Requires sentence-transformers (pip install 'casestack[embeddings]').
    """
    from casestack.api.deps import get_case_db
    import threading

    if _reembed_status.get(slug, {}).get("status") == "running":
        raise HTTPException(409, "Reembed already running for this case")

    db_path = get_case_db(slug)

    def _run():
        _reembed_status[slug] = {"status": "running"}
        try:
            from casestack.processors.page_embedder import PageEmbedder
            embedder = PageEmbedder()
            count = embedder.embed_corpus(db_path)
            # Invalidate the in-memory embedding cache so next query reloads
            from casestack.api.routes.ask import _emb_cache
            _emb_cache.pop(str(db_path), None)
            _reembed_status[slug] = {"status": "completed", "pages_embedded": count}
        except ImportError as exc:
            _reembed_status[slug] = {"status": "failed", "error": str(exc)}
        except Exception as exc:
            _reembed_status[slug] = {"status": "failed", "error": str(exc)}

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}


@router.get("/cases/{slug}/reembed/status")
def reembed_status(slug: str):
    """Get page embedding generation status."""
    return _reembed_status.get(slug, {"status": "never_run"})
