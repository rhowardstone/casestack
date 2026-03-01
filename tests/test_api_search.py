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
        Document(id="doc-1", title="EFTA00001", source="other", category="other",
                 ocrText="Wire transfers to Deutsche Bank totalling four million"),
        Document(id="doc-2", title="EFTA00002", source="other", category="other",
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
    from casestack.api import deps
    deps.get_app_state.cache_clear()
    from casestack.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        c.post("/api/cases", json={
            "name": "Search Test", "slug": "search-test",
            "documents_dir": str(docs_dir),
        })
        # Create the case DB in the output dir
        db_path = tmp_path / "cases" / "search-test" / "output" / "search-test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _create_test_db(db_path)
        yield c
    os.environ.pop("CASESTACK_HOME", None)
    deps.get_app_state.cache_clear()


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
