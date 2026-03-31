"""Regression tests for _add_adjacent_context() in the ask API route.

PDFs are stored one-page-per-database-row.  Sentences that span a page
boundary are split: the end of a sentence is on page N while the beginning
was on page N-1.  The LLM sees "...notified by the Captain" without knowing
the subject, or "Out of 183 round signatures were missing" where "Out of"
is dangling because "183 of [N] required round signatures" started on the
previous page.

The fix: _add_adjacent_context() fetches the last 300 chars of the previous
page and the first 300 chars of the next page for each retrieved result and
prepends/appends them so the LLM has complete sentence context.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from casestack.api.routes.ask import _add_adjacent_context, _search_pages


@pytest.fixture
def three_page_db():
    """DB with one document having three pages where a sentence spans pages 1→2."""
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
        CREATE VIRTUAL TABLE pages_fts USING fts5(
            text_content,
            content='pages',
            content_rowid='id'
        );

        INSERT INTO documents VALUES (1, 'doc-abc', 'Report');
        -- Page 1 ends mid-sentence
        INSERT INTO pages VALUES (1, 1, 'doc-abc', 1,
            'The investigation found serious failures. Out of the required', 61);
        -- Page 2 continues the sentence and has new content
        INSERT INTO pages VALUES (2, 1, 'doc-abc', 2,
            '183 round signatures were missing during the observation period. Staff failed to conduct mandatory rounds.', 103);
        -- Page 3 is separate content
        INSERT INTO pages VALUES (3, 1, 'doc-abc', 3,
            'The warden was notified on August 10 at 6:30 am.', 48);

        INSERT INTO pages_fts(rowid, text_content) VALUES (1, 'The investigation found serious failures. Out of the required');
        INSERT INTO pages_fts(rowid, text_content) VALUES (2, '183 round signatures were missing during the observation period. Staff failed to conduct mandatory rounds.');
        INSERT INTO pages_fts(rowid, text_content) VALUES (3, 'The warden was notified on August 10 at 6:30 am.');
    """)
    conn.close()

    yield db_path
    db_path.unlink(missing_ok=True)


class TestAddAdjacentContext:
    def test_prepends_previous_page_tail(self, three_page_db):
        """Page 2's result should include the tail of page 1."""
        conn = sqlite3.connect(str(three_page_db))
        results = [{"doc_id": "doc-abc", "page_number": 2, "text": "183 round signatures were missing."}]
        _add_adjacent_context(conn, results, context_chars=300)
        conn.close()

        assert "Out of the required" in results[0]["text"]

    def test_appends_next_page_head(self, three_page_db):
        """Page 1's result should include the head of page 2."""
        conn = sqlite3.connect(str(three_page_db))
        results = [{"doc_id": "doc-abc", "page_number": 1, "text": "The investigation found serious failures."}]
        _add_adjacent_context(conn, results, context_chars=300)
        conn.close()

        assert "183 round signatures" in results[0]["text"]

    def test_first_page_has_no_prev(self, three_page_db):
        """First page should get next-page head but no prev-page tail."""
        conn = sqlite3.connect(str(three_page_db))
        results = [{"doc_id": "doc-abc", "page_number": 1, "text": "Page 1 content."}]
        _add_adjacent_context(conn, results, context_chars=300)
        conn.close()

        assert "[...]" in results[0]["text"]  # next-head marker present
        # Should not have double [...] at start (no prev)
        assert not results[0]["text"].startswith("[...]")

    def test_last_page_has_no_next(self, three_page_db):
        """Last page should get prev-page tail but no next-page head."""
        conn = sqlite3.connect(str(three_page_db))
        results = [{"doc_id": "doc-abc", "page_number": 3, "text": "The warden was notified."}]
        _add_adjacent_context(conn, results, context_chars=300)
        conn.close()

        text = results[0]["text"]
        assert "[...]" in text  # prev-tail marker
        # Check it ends with the original text, not a next-head suffix
        assert text.endswith("The warden was notified.")

    def test_no_adjacent_pages_leaves_text_unchanged(self, three_page_db):
        """A result with no adjacent pages in the DB is not modified."""
        conn = sqlite3.connect(str(three_page_db))
        # Use a page_number that has no neighbors in the DB
        results = [{"doc_id": "doc-abc", "page_number": 99, "text": "Isolated content."}]
        _add_adjacent_context(conn, results, context_chars=300)
        conn.close()

        assert results[0]["text"] == "Isolated content."

    def test_context_chars_limit_respected(self, three_page_db):
        """Only the last N chars of the previous page are prepended."""
        conn = sqlite3.connect(str(three_page_db))
        results = [{"doc_id": "doc-abc", "page_number": 2, "text": "183 round signatures."}]
        _add_adjacent_context(conn, results, context_chars=10)
        conn.close()

        # With context_chars=10, only the last 10 chars of page 1 are prepended
        text = results[0]["text"]
        # "the required"[-10:] = "e required"
        assert "e required" in text
        # The full page 1 text should NOT be prepended
        assert "The investigation found" not in text

    def test_empty_results_no_error(self, three_page_db):
        """Empty result list does not raise."""
        conn = sqlite3.connect(str(three_page_db))
        results = []
        _add_adjacent_context(conn, results)  # Should not raise
        conn.close()
        assert results == []

    def test_multiple_results_all_augmented(self, three_page_db):
        """All results in the list are augmented, not just the first."""
        conn = sqlite3.connect(str(three_page_db))
        results = [
            {"doc_id": "doc-abc", "page_number": 2, "text": "183 round signatures."},
            {"doc_id": "doc-abc", "page_number": 3, "text": "The warden was notified."},
        ]
        _add_adjacent_context(conn, results, context_chars=300)
        conn.close()

        assert "Out of the required" in results[0]["text"]   # prev tail for page 2
        assert "mandatory rounds" in results[1]["text"]       # prev tail for page 3

    def test_search_pages_includes_adjacent_context(self, three_page_db):
        """Integration: _search_pages() results include adjacent page context."""
        # Page 2 matches "signatures"
        results = _search_pages(three_page_db, ["signatures"])
        assert len(results) >= 1
        page2 = next((r for r in results if r["page_number"] == 2), None)
        assert page2 is not None
        # Should have context from page 1 prepended
        assert "Out of the required" in page2["text"]
