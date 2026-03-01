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
        try:
            run_ingest(case, skip_overrides=overrides or None)
            conn = state._connect()
            conn.execute(
                "UPDATE ingest_runs SET status='completed', completed_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), run_id),
            )
            conn.commit()
            conn.close()
            _running_ingest[slug]["status"] = "completed"
        except Exception as exc:
            conn = state._connect()
            conn.execute(
                "UPDATE ingest_runs SET status='failed', error_message=?, completed_at=? WHERE id=?",
                (str(exc), datetime.now(timezone.utc).isoformat(), run_id),
            )
            conn.commit()
            conn.close()
            _running_ingest[slug]["status"] = "failed"

    thread = threading.Thread(target=_run, daemon=True)
    _running_ingest[slug] = {"thread": thread, "status": "running", "run_id": run_id}
    thread.start()

    return {"status": "started", "run_id": run_id}


@router.get("/cases/{slug}/ingest/status")
def ingest_status(slug: str):
    """Get current ingest status."""
    if slug in _running_ingest:
        return {
            "status": _running_ingest[slug]["status"],
            "run_id": _running_ingest[slug].get("run_id"),
        }
    state = get_app_state()
    conn = state._connect()
    row = conn.execute(
        "SELECT * FROM ingest_runs WHERE case_slug = ? ORDER BY id DESC LIMIT 1",
        (slug,),
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"status": "never_run"}
