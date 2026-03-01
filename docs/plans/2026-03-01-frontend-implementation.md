# CaseStack Frontend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a FastAPI backend + React SPA that replaces Datasette as the serving layer, giving CaseStack a layperson-friendly web UI with a case wizard, live ingest dashboard, unified search, entity viewer, image gallery, transcript browser, heatmap, and AI assistant.

**Architecture:** Single-process FastAPI server serves both the API (`/api/*`, `/ws/*`) and the pre-built React SPA (`/*`). App state lives in `~/.casestack/casestack.db`. Per-case data lives in existing per-case SQLite DBs. The React SPA is pre-built and bundled as package data in the pip distribution.

**Tech Stack:** Python (FastAPI, uvicorn, aiosqlite), React 18 + TypeScript + Vite, d3-force, Leaflet, marked.js

**Design doc:** `docs/plans/2026-03-01-frontend-design.md` (777 lines, all details)

---

## Phase 1: Backend Foundation

Get a FastAPI server running that can serve a placeholder page, manage app state, and handle case CRUD. This is the skeleton everything else builds on.

### Task 1: Add server dependencies + `casestack start` command

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/casestack/cli.py`
- Test: `tests/test_cli_start.py`

**Step 1: Write test**

```python
# tests/test_cli_start.py
"""Tests for the `casestack start` command."""
import threading
import time

import httpx
import pytest


def test_start_command_exists():
    """The start command is registered."""
    from click.testing import CliRunner
    from casestack.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--help"])
    assert result.exit_code == 0
    assert "Start CaseStack web interface" in result.output


def test_serve_datasette_command_exists():
    """The old serve command is renamed to serve-datasette."""
    from click.testing import CliRunner
    from casestack.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["serve-datasette", "--help"])
    assert result.exit_code == 0
```

**Step 2: Run test, verify fail**

Run: `cd /mnt/c/Users/rhowa/Documents/startups/casestack && python -m pytest tests/test_cli_start.py -v`

**Step 3: Update pyproject.toml**

Add to `[project.optional-dependencies]`:
```toml
server = ["fastapi>=0.100", "uvicorn[standard]>=0.20", "aiosqlite>=0.20"]
```

Add to existing `ask` extra: already has `starlette>=0.27, uvicorn>=0.24` — keep those.

Add package data:
```toml
[tool.setuptools.package-data]
casestack = ["static/**/*", "templates/**/*"]
```

Run: `pip install -e ".[server,dev]"`

**Step 4: Add `start` command and rename `serve` to `serve-datasette`**

In `cli.py`:
- Rename the existing `@cli.command()` decorated `serve` function: change `@cli.command()` above `def serve(...)` to `@cli.command("serve-datasette")`
- Add a `serve` alias that prints a deprecation notice and calls `serve-datasette`
- Add the `start` command:

```python
@cli.command()
@click.option("--port", "-p", default=8000, help="Port for web interface")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--no-browser", is_flag=True, help="Don't open browser automatically")
def start(port, host, no_browser):
    """Start CaseStack web interface."""
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Server dependencies not installed.[/red]\n"
            "Install with: pip install 'casestack[server]'"
        )
        sys.exit(1)

    from casestack.api.app import create_app

    if not no_browser:
        import webbrowser
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    console.print(f"[bold]CaseStack[/bold] running at http://{host}:{port}")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
```

**Step 5: Run test, verify pass**

Run: `python -m pytest tests/test_cli_start.py -v`

**Step 6: Commit**

```bash
git add pyproject.toml src/casestack/cli.py tests/test_cli_start.py
git commit -m "feat: add casestack start command, rename serve to serve-datasette"
```

---

### Task 2: App state database

**Files:**
- Create: `src/casestack/api/__init__.py`
- Create: `src/casestack/api/state.py`
- Test: `tests/test_api_state.py`

**Step 1: Write test**

```python
# tests/test_api_state.py
"""Tests for app state database."""
from pathlib import Path

from casestack.api.state import AppState


def test_init_creates_tables(tmp_path):
    db_path = tmp_path / "state.db"
    state = AppState(db_path)
    state.init_db()
    # Verify tables exist
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "cases" in tables
    assert "ingest_runs" in tables
    assert "conversations" in tables
    assert "conversation_messages" in tables


def test_register_and_list_cases(tmp_path):
    state = AppState(tmp_path / "state.db")
    state.init_db()
    state.register_case(
        slug="test-case",
        name="Test Case",
        description="A test",
        case_yaml_path="/tmp/case.yaml",
        output_dir="/tmp/output/test-case",
        documents_dir="/tmp/docs",
    )
    cases = state.list_cases()
    assert len(cases) == 1
    assert cases[0]["slug"] == "test-case"
    assert cases[0]["name"] == "Test Case"


def test_get_case(tmp_path):
    state = AppState(tmp_path / "state.db")
    state.init_db()
    state.register_case(
        slug="my-case", name="My Case", description="",
        case_yaml_path="/tmp/c.yaml", output_dir="/tmp/o",
        documents_dir="/tmp/d",
    )
    case = state.get_case("my-case")
    assert case is not None
    assert case["name"] == "My Case"
    assert state.get_case("nonexistent") is None


def test_delete_case(tmp_path):
    state = AppState(tmp_path / "state.db")
    state.init_db()
    state.register_case(
        slug="del-me", name="Delete Me", description="",
        case_yaml_path="/x", output_dir="/x", documents_dir="/x",
    )
    assert state.get_case("del-me") is not None
    state.delete_case("del-me")
    assert state.get_case("del-me") is None


def test_update_case_stats(tmp_path):
    state = AppState(tmp_path / "state.db")
    state.init_db()
    state.register_case(
        slug="s", name="S", description="",
        case_yaml_path="/x", output_dir="/x", documents_dir="/x",
    )
    state.update_case_stats("s", document_count=100, page_count=5000)
    case = state.get_case("s")
    assert case["document_count"] == 100
    assert case["page_count"] == 5000
```

**Step 2: Run test, verify fail**

Run: `python -m pytest tests/test_api_state.py -v`

**Step 3: Implement `state.py`**

```python
# src/casestack/api/__init__.py
# (empty)
```

```python
# src/casestack/api/state.py
"""App state database — tracks registered cases, ingest runs, conversations."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class AppState:
    """Manages the CaseStack app state SQLite database."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_db(self) -> None:
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                case_yaml_path TEXT NOT NULL,
                output_dir TEXT NOT NULL,
                documents_dir TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_opened_at TEXT,
                document_count INTEGER DEFAULT 0,
                page_count INTEGER DEFAULT 0,
                image_count INTEGER DEFAULT 0,
                transcript_count INTEGER DEFAULT 0,
                entity_count INTEGER DEFAULT 0,
                db_size_bytes INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS ingest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_slug TEXT NOT NULL REFERENCES cases(slug) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT DEFAULT 'running',
                current_step TEXT,
                progress_json TEXT,
                error_message TEXT,
                stats_json TEXT
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                case_slug TEXT NOT NULL REFERENCES cases(slug) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                title TEXT
            );

            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources_json TEXT,
                queries_json TEXT,
                created_at TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()

    def register_case(self, *, slug: str, name: str, description: str,
                      case_yaml_path: str, output_dir: str,
                      documents_dir: str) -> dict:
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO cases
               (slug, name, description, case_yaml_path, output_dir,
                documents_dir, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (slug, name, description, case_yaml_path, output_dir,
             documents_dir, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM cases WHERE slug = ?", (slug,)).fetchone()
        conn.close()
        return dict(row)

    def list_cases(self) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM cases ORDER BY last_opened_at DESC, created_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_case(self, slug: str) -> dict | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM cases WHERE slug = ?", (slug,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_case(self, slug: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM cases WHERE slug = ?", (slug,))
        conn.commit()
        conn.close()

    def update_case_stats(self, slug: str, **kwargs) -> None:
        allowed = {"document_count", "page_count", "image_count",
                   "transcript_count", "entity_count", "db_size_bytes",
                   "last_opened_at"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        conn = self._connect()
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE cases SET {sets} WHERE slug = ?",
                     (*fields.values(), slug))
        conn.commit()
        conn.close()
```

**Step 4: Run test, verify pass**

Run: `python -m pytest tests/test_api_state.py -v`

**Step 5: Commit**

```bash
git add src/casestack/api/__init__.py src/casestack/api/state.py tests/test_api_state.py
git commit -m "feat: add app state database for case tracking"
```

---

### Task 3: FastAPI app factory + case CRUD routes

**Files:**
- Create: `src/casestack/api/app.py`
- Create: `src/casestack/api/deps.py`
- Create: `src/casestack/api/routes/__init__.py`
- Create: `src/casestack/api/routes/cases.py`
- Test: `tests/test_api_cases.py`

**Step 1: Write test**

```python
# tests/test_api_cases.py
"""Tests for case CRUD API routes."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """Create a test client with a temporary state DB."""
    import os
    os.environ["CASESTACK_HOME"] = str(tmp_path)
    from casestack.api.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    os.environ.pop("CASESTACK_HOME", None)


def test_list_cases_empty(client):
    r = client.get("/api/cases")
    assert r.status_code == 200
    assert r.json() == []


def test_create_case(client, tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "test.pdf").write_bytes(b"%PDF-1.4 fake")
    r = client.post("/api/cases", json={
        "name": "Test Case",
        "slug": "test-case",
        "documents_dir": str(docs_dir),
    })
    assert r.status_code == 201
    data = r.json()
    assert data["slug"] == "test-case"
    assert data["name"] == "Test Case"


def test_get_case(client, tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    client.post("/api/cases", json={
        "name": "Get Me", "slug": "get-me",
        "documents_dir": str(docs_dir),
    })
    r = client.get("/api/cases/get-me")
    assert r.status_code == 200
    assert r.json()["name"] == "Get Me"


def test_get_case_not_found(client):
    r = client.get("/api/cases/nonexistent")
    assert r.status_code == 404


def test_delete_case(client, tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    client.post("/api/cases", json={
        "name": "Del", "slug": "del",
        "documents_dir": str(docs_dir),
    })
    r = client.delete("/api/cases/del")
    assert r.status_code == 204
    assert client.get("/api/cases/del").status_code == 404


def test_scan_directory(client, tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "a.pdf").write_bytes(b"%PDF")
    (docs_dir / "b.pdf").write_bytes(b"%PDF")
    (docs_dir / "c.mp4").write_bytes(b"\x00")
    (docs_dir / "d.txt").write_text("hello")
    r = client.post("/api/cases/scan", json={"path": str(docs_dir)})
    assert r.status_code == 200
    data = r.json()
    assert data["pdf"] == 2
    assert data["media"] >= 1
    assert data["text"] >= 1
```

**Step 2: Run test, verify fail**

Run: `python -m pytest tests/test_api_cases.py -v`

**Step 3: Implement app factory, deps, and cases route**

```python
# src/casestack/api/deps.py
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
```

```python
# src/casestack/api/app.py
"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from casestack.api.deps import get_app_state


def create_app() -> FastAPI:
    app = FastAPI(title="CaseStack", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize app state DB
    get_app_state()

    # Register API routes
    from casestack.api.routes import cases
    app.include_router(cases.router, prefix="/api")

    # Serve static frontend (if built)
    import importlib.resources
    static_dir = importlib.resources.files("casestack") / "static"
    if static_dir.is_dir() and (static_dir / "index.html").is_file():
        # SPA fallback: serve index.html for all non-API routes
        from fastapi.responses import FileResponse

        app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

        @app.get("/{path:path}")
        async def spa_fallback(path: str):
            return FileResponse(str(static_dir / "index.html"))
    else:
        @app.get("/")
        async def placeholder():
            return {"status": "CaseStack API running", "frontend": "not built yet"}

    return app
```

```python
# src/casestack/api/routes/__init__.py
# (empty)
```

```python
# src/casestack/api/routes/cases.py
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
    return get_app_state().list_cases()


@router.post("/cases", status_code=201)
def create_case(body: CaseCreate):
    state = get_app_state()
    docs_dir = Path(body.documents_dir)
    if not docs_dir.is_dir():
        raise HTTPException(400, f"Directory not found: {body.documents_dir}")

    # Create case.yaml
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
```

**Step 4: Run test, verify pass**

Run: `python -m pytest tests/test_api_cases.py -v`

**Step 5: Commit**

```bash
git add src/casestack/api/ tests/test_api_cases.py
git commit -m "feat: FastAPI app factory with case CRUD routes"
```

---

### Task 4: Pipeline and ingest routes

**Files:**
- Create: `src/casestack/api/routes/pipeline.py`
- Create: `src/casestack/api/routes/ingest.py`
- Test: `tests/test_api_pipeline.py`

**Step 1: Write test**

```python
# tests/test_api_pipeline.py
"""Tests for pipeline manifest and ingest routes."""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    os.environ["CASESTACK_HOME"] = str(tmp_path)
    from casestack.api.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    os.environ.pop("CASESTACK_HOME", None)


def test_global_manifest(client):
    r = client.get("/api/pipeline/manifest")
    assert r.status_code == 200
    manifest = r.json()
    assert len(manifest) >= 10
    ids = [s["id"] for s in manifest]
    assert "ocr" in ids
    assert "embeddings" in ids


def test_case_pipeline(client, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    client.post("/api/cases", json={
        "name": "P", "slug": "p", "documents_dir": str(docs),
    })
    r = client.get("/api/cases/p/pipeline")
    assert r.status_code == 200
    data = r.json()
    assert "steps" in data
    assert any(s["id"] == "ocr" for s in data["steps"])
    # Check each step has 'enabled' field
    for step in data["steps"]:
        assert "enabled" in step
```

**Step 2: Run test, verify fail**

**Step 3: Implement routes**

```python
# src/casestack/api/routes/pipeline.py
"""Pipeline manifest and configuration routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from casestack.api.deps import get_app_state
from casestack.pipeline import get_manifest

router = APIRouter()


@router.get("/pipeline/manifest")
def global_manifest():
    """Return the global pipeline manifest (no case context)."""
    return get_manifest()


@router.get("/cases/{slug}/pipeline")
def case_pipeline(slug: str):
    """Return pipeline manifest with case-specific enablement."""
    state = get_app_state()
    case_info = state.get_case(slug)
    if not case_info:
        raise HTTPException(404, "Case not found")

    from casestack.case import CaseConfig
    case_yaml = Path(case_info["case_yaml_path"])
    if case_yaml.exists():
        case = CaseConfig.from_yaml(case_yaml)
    else:
        case = CaseConfig(name=case_info["name"], slug=slug)

    manifest = get_manifest()
    for step in manifest:
        step["enabled"] = case.is_step_enabled(step["id"])
    return {"steps": manifest, "pipeline_overrides": case.pipeline}
```

```python
# src/casestack/api/routes/ingest.py
"""Ingest start/stop/status routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from casestack.api.deps import get_app_state

router = APIRouter()

# In-memory tracking of running ingest (v1: single ingest at a time)
_running_ingest: dict = {}  # slug -> {"thread": Thread, "status": "running"}


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
    import json
    from datetime import datetime, timezone

    case_yaml = Path(case_info["case_yaml_path"])
    case = CaseConfig.from_yaml(case_yaml)

    overrides = {}
    if body and body.pipeline_overrides:
        overrides = body.pipeline_overrides

    # Record ingest run
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
    # Check DB for last run
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
```

Register both routers in `app.py` — add after the cases import:
```python
from casestack.api.routes import cases, pipeline, ingest
app.include_router(cases.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
```

**Step 4: Run test, verify pass**

Run: `python -m pytest tests/test_api_pipeline.py -v`

**Step 5: Commit**

```bash
git add src/casestack/api/routes/pipeline.py src/casestack/api/routes/ingest.py \
    src/casestack/api/app.py tests/test_api_pipeline.py
git commit -m "feat: add pipeline manifest and ingest API routes"
```

---

### Task 5: Search route (unified search across all data types)

**Files:**
- Create: `src/casestack/api/routes/search.py`
- Test: `tests/test_api_search.py`

**Step 1: Write test**

```python
# tests/test_api_search.py
"""Tests for unified search API."""
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient


def _create_test_db(db_path):
    """Create a minimal case DB with searchable content."""
    from casestack.exporters.sqlite_export import SqliteExporter
    from casestack.models.document import Document, Page

    docs = [
        Document(id="doc-1", title="EFTA00001", source="test", category="test",
                 ocrText="Wire transfers to Deutsche Bank totalling four million"),
        Document(id="doc-2", title="EFTA00002", source="test", category="test",
                 ocrText="Meeting notes from the foundation board"),
    ]
    pages = [
        Page(document_id="doc-1", page_number=1,
             text_content="Wire transfers to Deutsche Bank totalling four million",
             char_count=55),
        Page(document_id="doc-2", page_number=1,
             text_content="Meeting notes from the foundation board",
             char_count=40),
    ]
    exporter = SqliteExporter()
    exporter.export(documents=docs, persons=[], db_path=db_path, pages=pages)


@pytest.fixture
def client(tmp_path):
    os.environ["CASESTACK_HOME"] = str(tmp_path)
    from casestack.api.app import create_app

    # Create a case with a real DB
    app = create_app()
    with TestClient(app) as c:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        c.post("/api/cases", json={
            "name": "Search Test", "slug": "search-test",
            "documents_dir": str(docs_dir),
        })
        # Create the case DB
        from casestack.api.deps import get_app_state
        state = get_app_state()
        case = state.get_case("search-test")
        db_path = tmp_path / "cases" / "search-test" / "output" / "search-test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _create_test_db(db_path)
        yield c
    os.environ.pop("CASESTACK_HOME", None)


def test_search_pages(client):
    r = client.get("/api/cases/search-test/search", params={"q": "wire transfers"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] > 0
    assert any("wire" in r["snippet"].lower() for r in data["results"] if r.get("snippet"))


def test_search_no_results(client):
    r = client.get("/api/cases/search-test/search", params={"q": "xyznonexistent"})
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_search_requires_query(client):
    r = client.get("/api/cases/search-test/search")
    assert r.status_code == 422  # missing required param
```

**Step 2: Run test, verify fail**

**Step 3: Implement search route**

```python
# src/casestack/api/routes/search.py
"""Unified search across all data types in a case."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from casestack.api.deps import get_app_state

router = APIRouter()


def _get_case_db(slug: str) -> Path:
    """Find the SQLite DB for a case."""
    state = get_app_state()
    case = state.get_case(slug)
    if not case:
        raise HTTPException(404, "Case not found")
    output_dir = Path(case["output_dir"])
    db_path = output_dir / f"{slug}.db"
    if not db_path.exists():
        raise HTTPException(404, f"Database not found. Run ingest first.")
    return db_path


@router.get("/cases/{slug}/search")
def search(slug: str, q: str = Query(...), type: str = Query("all"),
           offset: int = 0, limit: int = 50):
    """Unified search across pages, transcripts, images, entities."""
    db_path = _get_case_db(slug)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    results = []
    total = 0
    requested_types = set(type.split(",")) if type != "all" else {"pages", "transcripts", "images"}

    # Search pages via FTS5
    if "pages" in requested_types or "all" in requested_types:
        try:
            rows = conn.execute("""
                SELECT d.doc_id, d.title, p.page_number,
                       snippet(pages_fts, 0, '<mark>', '</mark>', '...', 64) as snippet,
                       rank
                FROM pages_fts
                JOIN pages p ON p.rowid = pages_fts.rowid
                JOIN documents d ON d.id = p.document_id
                WHERE pages_fts MATCH ?
                ORDER BY rank
                LIMIT ? OFFSET ?
            """, (q, limit, offset)).fetchall()
            for row in rows:
                results.append({
                    "type": "page",
                    "document_id": row["doc_id"],
                    "title": row["title"],
                    "page_number": row["page_number"],
                    "snippet": row["snippet"],
                    "rank": row["rank"],
                })
            count_row = conn.execute(
                "SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH ?", (q,)
            ).fetchone()
            total += count_row[0]
        except Exception:
            pass  # FTS table may not exist

    # Search transcripts via FTS5
    if "transcripts" in requested_types or "all" in requested_types:
        try:
            rows = conn.execute("""
                SELECT document_id,
                       snippet(transcripts_fts, 0, '<mark>', '</mark>', '...', 64) as snippet,
                       rank
                FROM transcripts_fts
                JOIN transcripts t ON t.rowid = transcripts_fts.rowid
                WHERE transcripts_fts MATCH ?
                LIMIT ? OFFSET ?
            """, (q, limit, offset)).fetchall()
            for row in rows:
                results.append({
                    "type": "transcript",
                    "document_id": row["document_id"],
                    "snippet": row["snippet"],
                    "rank": row["rank"],
                })
        except Exception:
            pass

    # Search image descriptions via FTS5
    if "images" in requested_types or "all" in requested_types:
        try:
            rows = conn.execute("""
                SELECT i.document_id, i.page_number, i.file_path, i.description,
                       snippet(images_fts, 0, '<mark>', '</mark>', '...', 64) as snippet,
                       rank
                FROM images_fts
                JOIN extracted_images i ON i.rowid = images_fts.rowid
                WHERE images_fts MATCH ?
                LIMIT ? OFFSET ?
            """, (q, limit, offset)).fetchall()
            for row in rows:
                results.append({
                    "type": "image",
                    "document_id": row["document_id"],
                    "page_number": row["page_number"],
                    "file_path": row["file_path"],
                    "snippet": row["snippet"],
                    "rank": row["rank"],
                })
        except Exception:
            pass

    conn.close()

    # Sort by rank (FTS5 rank is negative, lower = better)
    results.sort(key=lambda r: r.get("rank", 0))

    return {"total": total, "results": results[:limit]}
```

Register in `app.py`:
```python
from casestack.api.routes import cases, pipeline, ingest, search
# ... add:
app.include_router(search.router, prefix="/api")
```

**Step 4: Run test, verify pass**

Run: `python -m pytest tests/test_api_search.py -v`

**Step 5: Commit**

```bash
git add src/casestack/api/routes/search.py src/casestack/api/app.py tests/test_api_search.py
git commit -m "feat: add unified search API route"
```

---

### Task 6: Document, entity, image, transcript, and map routes

**Files:**
- Create: `src/casestack/api/routes/documents.py`
- Create: `src/casestack/api/routes/entities.py`
- Create: `src/casestack/api/routes/images.py`
- Create: `src/casestack/api/routes/transcripts.py`
- Create: `src/casestack/api/routes/map.py`
- Test: `tests/test_api_data_routes.py`

These are all straightforward SQLite query routes. They follow the same pattern as search: get case DB path, query, return JSON. I'll provide the implementations inline rather than full TDD since the pattern is established.

**Step 1: Write tests**

```python
# tests/test_api_data_routes.py
"""Tests for document, entity, image, transcript, and map routes."""
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient


def _create_test_db(db_path):
    from casestack.exporters.sqlite_export import SqliteExporter
    from casestack.models.document import Document, Page

    docs = [
        Document(id="doc-1", title="EFTA00001", source="test", category="test",
                 ocrText="Test document text content here"),
    ]
    pages = [
        Page(document_id="doc-1", page_number=1,
             text_content="Test document text content here", char_count=34),
        Page(document_id="doc-1", page_number=2,
             text_content="Second page of the document", char_count=27),
    ]
    exporter = SqliteExporter()
    exporter.export(documents=docs, persons=[], db_path=db_path, pages=pages)


@pytest.fixture
def client(tmp_path):
    os.environ["CASESTACK_HOME"] = str(tmp_path)
    from casestack.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        c.post("/api/cases", json={
            "name": "Data Test", "slug": "data-test",
            "documents_dir": str(docs_dir),
        })
        db_path = tmp_path / "cases" / "data-test" / "output" / "data-test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _create_test_db(db_path)
        yield c
    os.environ.pop("CASESTACK_HOME", None)


def test_list_documents(client):
    r = client.get("/api/cases/data-test/documents")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) >= 1
    assert docs[0]["doc_id"] == "doc-1"


def test_get_document(client):
    r = client.get("/api/cases/data-test/documents/doc-1")
    assert r.status_code == 200
    assert r.json()["title"] == "EFTA00001"


def test_get_document_pages(client):
    r = client.get("/api/cases/data-test/documents/doc-1/pages")
    assert r.status_code == 200
    pages = r.json()
    assert len(pages) == 2
    assert pages[0]["page_number"] == 1
```

**Step 2: Run test, verify fail**

**Step 3: Implement all data routes**

Each route file follows the same pattern: import `_get_case_db` from search (refactor it to a shared util in `deps.py`), open SQLite, query, return.

Implement `documents.py`, `entities.py`, `images.py`, `transcripts.py`, `map.py` — all SQLite SELECT queries against the case DB schema documented above.

Move `_get_case_db` from `search.py` to `deps.py` so all routes can use it.

Register all routers in `app.py`.

**Step 4: Run test, verify pass**

Run: `python -m pytest tests/test_api_data_routes.py -v`

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`

**Step 6: Commit**

```bash
git add src/casestack/api/ tests/test_api_data_routes.py
git commit -m "feat: add document, entity, image, transcript, and map API routes"
```

---

## Phase 2: Frontend Foundation

### Task 7: React + Vite project scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/styles/globals.css`
- Create: `Makefile`

**Step 1: Initialize the React project**

```bash
cd /mnt/c/Users/rhowa/Documents/startups/casestack
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install react-router-dom
npm install -D @types/react-router-dom
```

**Step 2: Configure Vite proxy**

```typescript
// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
```

**Step 3: Set up globals.css with design tokens**

```css
/* frontend/src/styles/globals.css */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --bg: #fafafa;
  --surface: #ffffff;
  --text: #1a1a2e;
  --text-muted: #6b7280;
  --accent: #2563eb;
  --accent-light: #dbeafe;
  --success: #16a34a;
  --warning: #d97706;
  --danger: #dc2626;
  --border: #e5e7eb;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
}
```

**Step 4: Set up App.tsx with routing**

```tsx
// frontend/src/App.tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import CaseList from './pages/CaseList'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CaseList />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
```

**Step 5: Set up API client**

```typescript
// frontend/src/api/client.ts
const BASE = '/api'

export async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}
```

**Step 6: Create placeholder CaseList page**

```tsx
// frontend/src/pages/CaseList.tsx
import { useEffect, useState } from 'react'
import { fetchJSON } from '../api/client'

interface Case {
  slug: string
  name: string
  description: string
  document_count: number
}

export default function CaseList() {
  const [cases, setCases] = useState<Case[]>([])

  useEffect(() => {
    fetchJSON<Case[]>('/cases').then(setCases)
  }, [])

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 32 }}>
      <h1>CaseStack</h1>
      <p>Document Intelligence Platform</p>
      {cases.length === 0 ? (
        <div style={{ marginTop: 32, padding: 24, background: '#fff', borderRadius: 8 }}>
          <h2>No cases yet</h2>
          <p>Create your first case to get started.</p>
        </div>
      ) : (
        cases.map(c => (
          <div key={c.slug} style={{ padding: 16, margin: '8px 0', background: '#fff', borderRadius: 8 }}>
            <h3>{c.name}</h3>
            <p>{c.document_count} documents</p>
          </div>
        ))
      )}
    </div>
  )
}
```

**Step 7: Create Makefile**

```makefile
# Makefile
.PHONY: frontend dev

frontend:
	cd frontend && npm run build
	rm -rf src/casestack/static
	cp -r frontend/dist src/casestack/static

dev:
	@echo "Run in two terminals:"
	@echo "  Terminal 1: uvicorn casestack.api.app:create_app --factory --reload --port 8000"
	@echo "  Terminal 2: cd frontend && npm run dev"
```

**Step 8: Verify dev mode works**

```bash
cd frontend && npm run dev     # should start on :5173
# In separate terminal:
# uvicorn casestack.api.app:create_app --factory --reload --port 8000
```

**Step 9: Build and copy to static/**

```bash
make frontend
```

**Step 10: Commit**

```bash
git add frontend/ Makefile src/casestack/static/
git commit -m "feat: scaffold React + Vite frontend with routing and API client"
```

---

### Task 8: New Case Wizard page

**Files:**
- Create: `frontend/src/pages/NewCaseWizard.tsx`
- Create: `frontend/src/components/PipelineToggle.tsx`
- Modify: `frontend/src/App.tsx` (add route)

**Step 1: Implement wizard with 4 steps**

The wizard has 4 steps:
1. **Directory** — text input for path, calls `POST /api/cases/scan` to get file counts
2. **Name** — name + slug (auto-derived) + description
3. **Pipeline** — toggle cards for each step, driven by `GET /api/pipeline/manifest` + scan results
4. **Review & Start** — summary, calls `POST /api/cases` then `POST /api/cases/:slug/ingest/start`

Each step is a React component within the wizard. The `PipelineToggle` component renders a single step card with toggle, description, dependency dimming, and expandable config.

**Step 2: Add route in App.tsx**

```tsx
<Route path="/new" element={<NewCaseWizard />} />
```

**Step 3: Build, verify in browser**

```bash
make frontend
python -c "from casestack.api.app import create_app; import uvicorn; uvicorn.run(create_app(), port=8000)" &
# Open http://localhost:8000/new
```

**Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: implement new case wizard with pipeline configuration"
```

---

### Task 9: Case Dashboard page

**Files:**
- Create: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/components/Layout.tsx`
- Create: `frontend/src/components/Sidebar.tsx`
- Create: `frontend/src/components/ProgressBar.tsx`
- Modify: `frontend/src/App.tsx`

**Step 1: Implement Layout with sidebar**

The `Layout` component provides the shell: a sidebar with navigation links (conditional on which pipeline steps ran) and a content area. The `Sidebar` shows: case name, nav links (Dashboard, Search, Entities, Images, Transcripts, Map, Ask AI), and a back-to-cases link.

**Step 2: Implement Dashboard**

Two modes:
- **Ingest running:** polls `GET /api/cases/:slug/ingest/status` every 2 seconds, shows progress bars per step
- **Ingest complete:** shows stat cards (documents, pages, images, transcripts) and quick-action buttons

**Step 3: Add routes**

```tsx
<Route path="/case/:slug" element={<Layout />}>
  <Route index element={<Dashboard />} />
  <Route path="search" element={<Search />} />
  {/* ... more routes added in later tasks */}
</Route>
```

**Step 4: Build, verify**

**Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat: implement case dashboard with progress tracking and layout shell"
```

---

### Task 10: Search page

**Files:**
- Create: `frontend/src/pages/Search.tsx`
- Create: `frontend/src/components/SearchResult.tsx`
- Create: `frontend/src/components/DocumentReader.tsx`
- Create: `frontend/src/hooks/useSearch.ts`

**Step 1: Implement debounced search hook**

```typescript
// frontend/src/hooks/useSearch.ts
// Custom hook: takes query string, returns { results, total, loading }
// Debounces API calls by 300ms
// Calls GET /api/cases/:slug/search?q=...
```

**Step 2: Implement SearchResult component**

Renders a single search result with type icon (page/transcript/image/entity), document title, snippet with `<mark>` tags rendered as HTML, and action buttons.

**Step 3: Implement DocumentReader component**

Inline expandable reader: fetches `GET /api/cases/:slug/documents/:doc_id/pages`, shows full page text with search term highlighting, prev/next page navigation.

**Step 4: Implement Search page**

Combines search input, filter sidebar (type checkboxes), and results list. Uses `useSearch` hook.

**Step 5: Build, verify search works end-to-end**

**Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat: implement unified search page with inline document reader"
```

---

### Task 11: Entity Viewer page

**Files:**
- Create: `frontend/src/pages/EntityViewer.tsx`
- Create: `frontend/src/components/EntityGraph.tsx`

**Step 1: Implement directory view**

Paginated entity list from `GET /api/cases/:slug/entities`. Filter by type, search by name. Each card shows name, type badge, mention count.

**Step 2: Implement graph view**

Uses d3-force. Install: `npm install d3-force d3-selection @types/d3-force @types/d3-selection`

Fetches `GET /api/cases/:slug/entities/graph`, renders force-directed graph with colored nodes (by type), weighted edges, drag/zoom.

Click a node → sidebar shows entity detail with connections and document references.

**Step 3: Build, verify**

**Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: implement entity viewer with directory and graph views"
```

---

### Task 12: Image Gallery page

**Files:**
- Create: `frontend/src/pages/ImageGallery.tsx`
- Create: `frontend/src/components/Lightbox.tsx`

**Step 1: Implement grid layout**

Fetches `GET /api/cases/:slug/images`, renders thumbnail grid. Lazy-loads images. Filter by has_description, source document.

**Step 2: Implement lightbox**

Click thumbnail → modal with full-size image, AI description, source document link.

**Step 3: Build, verify**

**Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: implement image gallery with lightbox"
```

---

### Task 13: Transcript Browser page

**Files:**
- Create: `frontend/src/pages/TranscriptBrowser.tsx`
- Create: `frontend/src/components/MediaPlayer.tsx`

**Step 1: Implement transcript list**

Fetches `GET /api/cases/:slug/transcripts`, shows media files with duration and format.

**Step 2: Implement media player with timestamped segments**

HTML5 `<audio>`/`<video>` element. Segments rendered as clickable rows that seek the player. Search within transcript.

**Step 3: Build, verify**

**Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: implement transcript browser with media playback"
```

---

### Task 14: Geographic Heatmap page

**Files:**
- Create: `frontend/src/pages/Heatmap.tsx`

**Step 1: Install Leaflet**

```bash
cd frontend && npm install leaflet @types/leaflet react-leaflet topojson-client @types/topojson-client
```

**Step 2: Implement choropleth map**

Fetches `GET /api/cases/:slug/map`, renders countries shaded by mention count. Click → sidebar with document citations.

**Step 3: Build, verify**

**Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: implement geographic heatmap with Leaflet"
```

---

### Task 15: AI Research Assistant page

**Files:**
- Create: `frontend/src/pages/AskAssistant.tsx`
- Create: `frontend/src/api/ask.ts`
- Create: `src/casestack/api/routes/ask.py`

**Step 1: Implement SSE client**

```typescript
// frontend/src/api/ask.ts
// POST /api/cases/:slug/ask with { question, conversation_id }
// Parse SSE events: status, queries, results, token, done, error
// Return async iterator of events
```

**Step 2: Implement backend ask route**

Port the RAG pipeline from `ask_server.py` into `src/casestack/api/routes/ask.py` as a FastAPI route with `StreamingResponse` for SSE.

**Step 3: Implement chat UI**

Message bubbles, markdown rendering (install `npm install marked`), source citation chips, streaming token display.

**Step 4: Build, verify end-to-end with an API key**

**Step 5: Commit**

```bash
git add frontend/src/ src/casestack/api/routes/ask.py
git commit -m "feat: implement AI research assistant with SSE streaming"
```

---

## Phase 3: Polish & Ship

### Task 16: IngestCallback protocol + WebSocket progress

**Files:**
- Modify: `src/casestack/ingest.py`
- Create: `src/casestack/api/websocket.py`
- Test: `tests/test_ingest_callback.py`

**Step 1: Write test for callback protocol**

```python
# tests/test_ingest_callback.py
def test_callback_receives_events(tmp_path):
    """IngestCallback receives step events during ingest."""
    # Create a minimal case with 1 text file
    # Run ingest with a recording callback
    # Assert callback received on_step_start, on_step_complete, on_complete
```

**Step 2: Add IngestCallback protocol to ingest.py**

```python
from typing import Protocol

class IngestCallback(Protocol):
    def on_step_start(self, step_id: str, total: int) -> None: ...
    def on_step_progress(self, step_id: str, current: int, total: int) -> None: ...
    def on_step_complete(self, step_id: str, stats: dict) -> None: ...
    def on_log(self, message: str, level: str) -> None: ...
    def on_complete(self, stats: dict) -> None: ...
    def on_error(self, step_id: str, message: str) -> None: ...
```

Add `callback: IngestCallback | None = None` parameter to `run_ingest()`. Add callback calls at each step boundary. Default behavior (callback=None) unchanged.

**Step 3: Implement WebSocket endpoint**

```python
# src/casestack/api/websocket.py
# FastAPI WebSocket endpoint at /ws/cases/{slug}/ingest
# Receives a WebSocketCallback that forwards events as JSON messages
```

**Step 4: Update Dashboard to use WebSocket instead of polling**

**Step 5: Commit**

```bash
git add src/casestack/ingest.py src/casestack/api/websocket.py tests/test_ingest_callback.py
git commit -m "feat: add IngestCallback protocol and WebSocket progress"
```

---

### Task 17: Build pipeline + packaging

**Files:**
- Modify: `pyproject.toml`
- Modify: `Makefile`
- Create: `.github/workflows/build.yml` (if using GitHub Actions)

**Step 1: Finalize pyproject.toml package data**

Ensure `src/casestack/static/**/*` is included in the wheel.

**Step 2: Build frontend and verify packaging**

```bash
make frontend
pip install -e ".[server]"
casestack start --no-browser &
curl http://localhost:8000/  # should return React SPA HTML
curl http://localhost:8000/api/cases  # should return JSON
```

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`

**Step 4: Commit**

```bash
git add pyproject.toml Makefile
git commit -m "feat: finalize build pipeline and packaging"
```

---

### Task 18: Update CaseList + polish

**Files:**
- Modify: `frontend/src/pages/CaseList.tsx`
- Create: `frontend/src/pages/CaseSettings.tsx`
- Modify: `frontend/src/App.tsx`

**Step 1: Polish CaseList**

Add "New Case" button linking to `/new`. Show case cards with name, doc count, last opened, ingest status. Link to case dashboard.

**Step 2: Implement CaseSettings page**

Edit case name/description, re-configure pipeline toggles, re-run ingest, delete case with confirmation.

**Step 3: Final build**

```bash
make frontend
```

**Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: polish case list and add case settings page"
```

---

## Existing code to reuse
- `pipeline.py` — `get_manifest()`, `get_enabled_steps()` drive wizard Step 3 and pipeline route
- `case.py` — `CaseConfig`, `from_yaml()`, `is_step_enabled()` for case loading
- `ingest.py` — `run_ingest()` for the ingest route (add callback, otherwise unchanged)
- `exporters/sqlite_export.py` — defines the case DB schema the data routes query
- `ask_server.py` / `ask.py` — RAG pipeline logic to port into FastAPI ask route
- `processors/` — all processors unchanged, called by ingest

## Files to create
- `src/casestack/api/` — entire package (app.py, deps.py, state.py, websocket.py, routes/*.py)
- `frontend/` — entire React app (package.json, vite config, all pages/components)
- `src/casestack/static/` — populated by build
- `Makefile`
- Tests: `test_cli_start.py`, `test_api_state.py`, `test_api_cases.py`, `test_api_pipeline.py`, `test_api_search.py`, `test_api_data_routes.py`, `test_ingest_callback.py`

## Files to modify
- `pyproject.toml` — add `server` extra, package data
- `src/casestack/cli.py` — add `start`, rename `serve` to `serve-datasette`
- `src/casestack/ingest.py` — add `IngestCallback` protocol parameter

## Verification
1. `python -m pytest tests/ -v` — all tests pass
2. `casestack start --no-browser` — server starts on :8000
3. `curl http://localhost:8000/` — returns React SPA
4. `curl http://localhost:8000/api/cases` — returns JSON
5. Browser: create case via wizard → ingest runs → search works → entity viewer → image gallery
6. `pip wheel .` — static/ bundled in wheel, no npm needed to install
