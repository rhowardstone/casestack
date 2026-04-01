"""Dependency injection for FastAPI routes."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from casestack.api.state import AppState


def get_casestack_home() -> Path:
    return Path(os.environ.get("CASESTACK_HOME", Path.home() / ".casestack"))


@lru_cache
def get_app_state() -> AppState:
    home = get_casestack_home()
    state = AppState(home / "casestack.db")
    state.init_db()
    return state


def _get_repo_root() -> Path:
    """Get the casestack repo/package root directory."""
    import casestack
    return Path(casestack.__file__).resolve().parent.parent.parent


def get_case_db(slug: str) -> Path:
    """Find the SQLite DB for a case.

    Checks multiple locations since CaseConfig.output_dir is relative
    to where ingest was run from.

    Raises HTTPException 404 if the case or its database is not found.
    """
    state = get_app_state()
    case = state.get_case(slug)
    if not case:
        raise HTTPException(404, "Case not found")

    db_name = f"{slug}.db"
    candidates = [
        Path(case["output_dir"]) / db_name,
        _get_repo_root() / "output" / slug / db_name,
        Path.cwd() / "output" / slug / db_name,
    ]

    for db_path in candidates:
        if db_path.exists() and db_path.stat().st_size > 0:
            return db_path

    raise HTTPException(404, "Database not found. Run ingest first.")
