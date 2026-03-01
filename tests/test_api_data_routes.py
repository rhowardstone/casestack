"""Tests for document, entity, image, transcript, and map routes."""
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient


def _create_test_db(db_path):
    """Create a case DB with documents, pages, persons, entities, and transcripts."""
    from casestack.exporters.sqlite_export import SqliteExporter
    from casestack.models.document import Document, Page, Person
    from casestack.models.forensics import (
        ExtractedEntity,
        ExtractedImage,
        Transcript,
    )

    docs = [
        Document(
            id="doc-1", title="EFTA00001", source="other", category="other",
            ocrText="Test document text content here",
            personIds=["p-0001", "p-0002"],
        ),
        Document(
            id="doc-2", title="EFTA00002", source="media", category="media",
            ocrText="Another document about meetings",
            personIds=["p-0001"],
        ),
    ]
    pages = [
        Page(document_id="doc-1", page_number=1,
             text_content="Test document text content here", char_count=34),
        Page(document_id="doc-1", page_number=2,
             text_content="Second page of the document", char_count=27),
        Page(document_id="doc-2", page_number=1,
             text_content="Another document about meetings", char_count=31),
    ]
    persons = [
        Person(id="p-0001", slug="alice-smith", name="Alice Smith",
               category="associate", shortBio="Test person"),
        Person(id="p-0002", slug="bob-jones", name="Bob Jones",
               category="associate", shortBio="Another person"),
    ]
    entities = [
        ExtractedEntity(document_id="doc-1", entity_type="GPE",
                        text="New York", confidence=0.95),
        ExtractedEntity(document_id="doc-1", entity_type="GPE",
                        text="London", confidence=0.9),
        ExtractedEntity(document_id="doc-2", entity_type="GPE",
                        text="New York", confidence=0.88),
        ExtractedEntity(document_id="doc-1", entity_type="PERSON",
                        text="Alice Smith", confidence=0.99, person_id="p-0001"),
    ]
    images = [
        ExtractedImage(document_id="doc-1", page_number=1, image_index=0,
                       width=800, height=600, format="png",
                       file_path="/tmp/fake-image.png",
                       description="A test image", size_bytes=1024),
    ]
    transcripts = [
        Transcript(source_path="/tmp/fake.mp4", document_id="doc-2",
                   text="Hello world this is a test transcript",
                   language="en", duration_seconds=120.5),
    ]

    exporter = SqliteExporter()
    exporter.export(
        documents=docs, persons=persons, db_path=db_path,
        pages=pages, entities=entities, images=images,
        transcripts=transcripts,
    )


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
            "name": "Data Test", "slug": "data-test",
            "documents_dir": str(docs_dir),
        })
        db_path = tmp_path / "cases" / "data-test" / "output" / "data-test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _create_test_db(db_path)
        yield c
    os.environ.pop("CASESTACK_HOME", None)
    deps.get_app_state.cache_clear()


# ---- Document routes ----

def test_list_documents(client):
    r = client.get("/api/cases/data-test/documents")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 2


def test_list_documents_pagination(client):
    r = client.get("/api/cases/data-test/documents", params={"limit": 1, "offset": 0})
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_get_document(client):
    r = client.get("/api/cases/data-test/documents/doc-1")
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "EFTA00001"
    assert data["doc_id"] == "doc-1"


def test_get_document_not_found(client):
    r = client.get("/api/cases/data-test/documents/nonexistent")
    assert r.status_code == 404


def test_get_document_pages(client):
    r = client.get("/api/cases/data-test/documents/doc-1/pages")
    assert r.status_code == 200
    pages = r.json()
    assert len(pages) == 2
    assert pages[0]["page_number"] == 1
    assert pages[1]["page_number"] == 2


def test_get_document_pages_not_found(client):
    r = client.get("/api/cases/data-test/documents/nonexistent/pages")
    assert r.status_code == 404


# ---- Entity routes ----

def test_list_entities(client):
    r = client.get("/api/cases/data-test/entities")
    assert r.status_code == 200
    entities = r.json()
    assert len(entities) == 2
    names = {e["name"] for e in entities}
    assert "Alice Smith" in names
    assert "Bob Jones" in names


def test_list_entities_filter_category(client):
    r = client.get("/api/cases/data-test/entities", params={"category": "associate"})
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_entity_graph(client):
    r = client.get("/api/cases/data-test/entities/graph")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert "edges" in data
    # Both persons appear in doc-1, so there should be a co-occurrence edge
    assert len(data["nodes"]) >= 1
    if data["edges"]:
        edge = data["edges"][0]
        assert "source" in edge
        assert "target" in edge
        assert "weight" in edge


# ---- Image routes ----

def test_list_images(client):
    r = client.get("/api/cases/data-test/images")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert len(data["images"]) == 1
    assert data["images"][0]["description"] == "A test image"


def test_get_image(client):
    r = client.get("/api/cases/data-test/images/1")
    assert r.status_code == 200
    data = r.json()
    assert data["width"] == 800
    assert data["document_id"] == "doc-1"


def test_get_image_not_found(client):
    r = client.get("/api/cases/data-test/images/999")
    assert r.status_code == 404


# ---- Transcript routes ----

def test_list_transcripts(client):
    r = client.get("/api/cases/data-test/transcripts")
    assert r.status_code == 200
    transcripts = r.json()
    assert len(transcripts) == 1
    assert transcripts[0]["language"] == "en"


def test_get_transcript(client):
    r = client.get("/api/cases/data-test/transcripts/doc-2")
    assert r.status_code == 200
    data = r.json()
    assert "Hello world" in data["text"]
    assert data["duration_seconds"] == 120.5


def test_get_transcript_not_found(client):
    r = client.get("/api/cases/data-test/transcripts/nonexistent")
    assert r.status_code == 404


# ---- Map route ----

def test_map_data(client):
    r = client.get("/api/cases/data-test/map")
    assert r.status_code == 200
    data = r.json()
    # We inserted 3 GPE entities: "New York" x2 and "London" x1
    assert len(data) == 2  # two distinct locations
    ny = next(d for d in data if d["location"] == "New York")
    assert ny["mentions"] == 2
    london = next(d for d in data if d["location"] == "London")
    assert london["mentions"] == 1


# ---- Case not found ----

def test_documents_case_not_found(client):
    r = client.get("/api/cases/nonexistent/documents")
    assert r.status_code == 404


def test_entities_case_not_found(client):
    r = client.get("/api/cases/nonexistent/entities")
    assert r.status_code == 404
