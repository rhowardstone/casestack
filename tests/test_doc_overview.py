"""Regression tests for _fetch_doc_overview_pages() in the ask API route.

When a question names a specific document by EFTA ID (e.g. "What is in
EFTA00039421?"), the FTS5 index cannot match by document title — it only
indexes page text. Without this fix the system would retrieve random pages
from that document (or none at all) and give wrong answers.

The fix: detect EFTA-style document IDs in the question and inject the first
few pages of those documents directly, before FTS5 results.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from casestack.api.routes.ask import _fetch_doc_overview_pages


@pytest.fixture
def test_db():
    """Create a minimal in-memory database with the CaseStack schema."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            doc_id TEXT NOT NULL,
            title TEXT NOT NULL
        );
        CREATE TABLE pages (
            id INTEGER PRIMARY KEY,
            document_id INTEGER,
            doc_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text_content TEXT NOT NULL,
            char_count INTEGER DEFAULT 0
        );
        INSERT INTO documents VALUES (1, 'doc-abc123', 'EFTA00039421');
        INSERT INTO documents VALUES (2, 'doc-def456', 'EFTA00039025');
        INSERT INTO pages VALUES (1, 1, 'doc-abc123', 1, 'Page 1 of Maxwell case brief', 30);
        INSERT INTO pages VALUES (2, 1, 'doc-abc123', 2, 'Page 2 of Maxwell case brief', 30);
        INSERT INTO pages VALUES (3, 1, 'doc-abc123', 3, 'Page 3 of Maxwell case brief', 30);
        INSERT INTO pages VALUES (4, 1, 'doc-abc123', 4, 'Page 4 content', 15);
        INSERT INTO pages VALUES (5, 1, 'doc-abc123', 5, 'Page 5 content', 15);
        INSERT INTO pages VALUES (6, 1, 'doc-abc123', 6, 'Page 6 content', 15);
        INSERT INTO pages VALUES (7, 2, 'doc-def456', 1, 'OIG report page 1', 18);
    """)
    conn.close()

    yield db_path
    db_path.unlink(missing_ok=True)


class TestFetchDocOverviewPages:
    def test_returns_empty_for_no_efta_in_question(self, test_db):
        """Questions without EFTA IDs produce no override pages."""
        result = _fetch_doc_overview_pages(test_db, "What happened at MCC?", set())
        assert result == []

    def test_fetches_first_five_pages(self, test_db):
        """Fetches up to 5 pages of the referenced document."""
        result = _fetch_doc_overview_pages(test_db, "What is in EFTA00039421?", set())
        assert len(result) == 5
        page_nums = [r["page_number"] for r in result]
        assert page_nums == [1, 2, 3, 4, 5]

    def test_returns_correct_doc_id(self, test_db):
        result = _fetch_doc_overview_pages(test_db, "Summarize EFTA00039421.", set())
        assert all(r["doc_id"] == "doc-abc123" for r in result)

    def test_skips_already_seen_pages(self, test_db):
        """Pages already in 'seen' set are not duplicated."""
        seen = {("doc-abc123", 1), ("doc-abc123", 2)}
        result = _fetch_doc_overview_pages(test_db, "What is in EFTA00039421?", seen)
        page_nums = [r["page_number"] for r in result]
        assert 1 not in page_nums
        assert 2 not in page_nums

    def test_multiple_efta_ids_in_question(self, test_db):
        """When two EFTA IDs appear in the question, both are fetched."""
        result = _fetch_doc_overview_pages(
            test_db,
            "Compare EFTA00039421 and EFTA00039025",
            set(),
        )
        doc_ids = {r["doc_id"] for r in result}
        assert "doc-abc123" in doc_ids
        assert "doc-def456" in doc_ids

    def test_unknown_efta_id_returns_empty(self, test_db):
        """An EFTA ID not in the database returns no results (no crash)."""
        result = _fetch_doc_overview_pages(
            test_db, "What is in EFTA00099999?", set()
        )
        assert result == []

    def test_output_has_required_keys(self, test_db):
        result = _fetch_doc_overview_pages(test_db, "Tell me about EFTA00039421.", set())
        assert result
        for r in result:
            assert "doc_id" in r
            assert "title" in r
            assert "page_number" in r
            assert "text" in r
            assert "snippet" in r

    def test_case_insensitive_efta_id(self, test_db):
        """EFTA IDs in the question are matched case-insensitively."""
        result_lower = _fetch_doc_overview_pages(
            test_db, "What is in efta00039421?", set()
        )
        result_upper = _fetch_doc_overview_pages(
            test_db, "What is in EFTA00039421?", set()
        )
        assert len(result_lower) == len(result_upper)
