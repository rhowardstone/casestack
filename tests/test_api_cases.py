"""Tests for case CRUD API routes."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """Create a test client with a temporary state DB."""
    import os
    os.environ["CASESTACK_HOME"] = str(tmp_path)
    # Clear any cached state from previous tests
    from casestack.api import deps
    deps.get_app_state.cache_clear()
    from casestack.api.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    os.environ.pop("CASESTACK_HOME", None)
    deps.get_app_state.cache_clear()


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
