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


def get_case_db(slug: str) -> Path:
    """Find the SQLite DB for a case.

    Raises HTTPException 404 if the case or its database is not found.
    """
    state = get_app_state()
    case = state.get_case(slug)
    if not case:
        raise HTTPException(404, "Case not found")
    output_dir = Path(case["output_dir"])
    db_path = output_dir / f"{slug}.db"
    if not db_path.exists():
        raise HTTPException(404, "Database not found. Run ingest first.")
    return db_path
