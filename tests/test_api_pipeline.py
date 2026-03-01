"""Tests for pipeline manifest and ingest routes."""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    os.environ["CASESTACK_HOME"] = str(tmp_path)
    from casestack.api import deps
    deps.get_app_state.cache_clear()
    from casestack.api.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    os.environ.pop("CASESTACK_HOME", None)
    deps.get_app_state.cache_clear()


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
    for step in data["steps"]:
        assert "enabled" in step
