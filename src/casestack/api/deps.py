"""Dependency injection for FastAPI routes."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from casestack.api.state import AppState


def get_casestack_home() -> Path:
    return Path(os.environ.get("CASESTACK_HOME", Path.home() / ".casestack"))


@lru_cache
def get_app_state() -> AppState:
    home = get_casestack_home()
    state = AppState(home / "casestack.db")
    state.init_db()
    return state
