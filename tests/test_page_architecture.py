"""Tests for the page-level architecture (documents + pages + pages_fts).

Covers:
- Page model creation and validation
- ProcessingResult with pages field
- SQLite exporter schema (documents, pages, pages_fts tables)
- FTS5 search returns page-level results
- Round-trip: ingest text files -> query pages_fts -> get results with page numbers
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from casestack.models.document import Document, Page, ProcessingResult


# ---------------------------------------------------------------------------
# Page model tests
# ---------------------------------------------------------------------------


class TestPageModel:
    def test_create_page(self):
        page = Page(
            document_id="doc-001",
            page_number=1,
            text_content="Hello world",
            char_count=11,
        )
        assert page.document_id == "doc-001"
        assert page.page_number == 1
        assert page.text_content == "Hello world"
        assert page.char_count == 11

    def test_page_serialization_roundtrip(self):
        page = Page(
            document_id="doc-002",
            page_number=5,
            text_content="Some legal text about contracts and obligations.",
            char_count=48,
        )
        json_str = page.model_dump_json()
        restored = Page.model_validate_json(json_str)
        assert restored == page

    def test_processing_result_with_pages(self):
        doc = Document(
            id="doc-001",
            title="Test Document",
            source="local",
            category="other",
            ocrText="Page one text\n\nPage two text",
        )
        pages = [
            Page(document_id="doc-001", page_number=1, text_content="Page one text", char_count=13),
            Page(document_id="doc-001", page_number=2, text_content="Page two text", char_count=13),
        ]
        result = ProcessingResult(
            source_path="/tmp/test.pdf",
            document=doc,
            pages=pages,
            processing_time_ms=100,
        )
        assert len(result.pages) == 2
        assert result.pages[0].page_number == 1
        assert result.pages[1].page_number == 2

    def test_processing_result_default_empty_pages(self):
        result = ProcessingResult(
            source_path="/tmp/test.pdf",
            processing_time_ms=0,
        )
        assert result.pages == []

    def test_processing_result_serialization_with_pages(self):
        doc = Document(
            id="doc-003",
            title="Serialization Test",
            source="local",
            category="legal",
        )
        pages = [
            Page(document_id="doc-003", page_number=1, text_content="First page", char_count=10),
        ]
        result = ProcessingResult(
            source_path="/tmp/test.pdf",
            document=doc,
            pages=pages,
            processing_time_ms=50,
        )
        json_str = result.model_dump_json()
        restored = ProcessingResult.model_validate_json(json_str)
        assert len(restored.pages) == 1
        assert restored.pages[0].text_content == "First page"
        assert restored.document is not None
        assert restored.document.id == "doc-003"


# ---------------------------------------------------------------------------
# SQLite exporter tests
# ---------------------------------------------------------------------------


class TestSqliteExporterSchema:
    def _make_test_data(self):
        """Create test documents and pages."""
        docs = [
            Document(
                id="doc-alpha",
                title="Alpha Document",
                source="court-filing",
                category="legal",
                summary="Alpha summary",
                ocrText="Page 1 alpha text\n\nPage 2 alpha text",
                tags=["alpha", "test"],
            ),
            Document(
                id="doc-beta",
                title="Beta Document",
                source="foia",
                category="government",
                summary="Beta summary",
                ocrText="Beta single page content about government secrets",
                tags=["beta"],
            ),
        ]
        pages = [
            Page(document_id="doc-alpha", page_number=1, text_content="Page 1 alpha text", char_count=17),
            Page(document_id="doc-alpha", page_number=2, text_content="Page 2 alpha text", char_count=17),
            Page(document_id="doc-beta", page_number=1, text_content="Beta single page content about government secrets", char_count=50),
        ]
        return docs, pages

    def test_creates_core_tables(self):
        from casestack.exporters.sqlite_export import SqliteExporter

        docs, pages = self._make_test_data()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            exporter = SqliteExporter()
            exporter.export(documents=docs, persons=[], db_path=db_path, pages=pages)

            conn = sqlite3.connect(str(db_path))
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            conn.close()

            assert "documents" in tables
            assert "pages" in tables
            assert "pages_fts" in tables
            assert "persons" in tables
            assert "document_persons" in tables

    def test_documents_table_populated(self):
        from casestack.exporters.sqlite_export import SqliteExporter

        docs, pages = self._make_test_data()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            exporter = SqliteExporter()
            exporter.export(documents=docs, persons=[], db_path=db_path, pages=pages)

            conn = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            assert count == 2

            row = conn.execute(
                "SELECT doc_id, title, total_pages, total_chars FROM documents WHERE doc_id = ?",
                ("doc-alpha",),
            ).fetchone()
            assert row is not None
            assert row[0] == "doc-alpha"
            assert row[1] == "Alpha Document"
            assert row[2] == 2  # total_pages
            assert row[3] == 34  # total_chars (17 + 17)
            conn.close()

    def test_pages_table_populated(self):
        from casestack.exporters.sqlite_export import SqliteExporter

        docs, pages = self._make_test_data()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            exporter = SqliteExporter()
            exporter.export(documents=docs, persons=[], db_path=db_path, pages=pages)

            conn = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            assert count == 3

            rows = conn.execute(
                "SELECT doc_id, page_number, text_content, char_count FROM pages"
                " WHERE doc_id = ? ORDER BY page_number",
                ("doc-alpha",),
            ).fetchall()
            assert len(rows) == 2
            assert rows[0][1] == 1  # page_number
            assert rows[0][2] == "Page 1 alpha text"
            assert rows[1][1] == 2
            assert rows[1][2] == "Page 2 alpha text"

            # Verify FK relationship
            alpha_doc_id = conn.execute(
                "SELECT id FROM documents WHERE doc_id = ?", ("doc-alpha",)
            ).fetchone()[0]
            page_fk = conn.execute(
                "SELECT document_id FROM pages WHERE doc_id = ? LIMIT 1",
                ("doc-alpha",),
            ).fetchone()[0]
            assert page_fk == alpha_doc_id
            conn.close()

    def test_fts5_search_returns_page_level_results(self):
        from casestack.exporters.sqlite_export import SqliteExporter

        docs, pages = self._make_test_data()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            exporter = SqliteExporter()
            exporter.export(documents=docs, persons=[], db_path=db_path, pages=pages)

            conn = sqlite3.connect(str(db_path))

            # Search for "alpha" -- should match pages from doc-alpha
            results = conn.execute(
                """SELECT p.doc_id, p.page_number, p.text_content
                   FROM pages_fts
                   JOIN pages p ON p.id = pages_fts.rowid
                   WHERE pages_fts MATCH 'alpha'
                   ORDER BY p.doc_id, p.page_number""",
            ).fetchall()
            assert len(results) == 2
            assert results[0][0] == "doc-alpha"
            assert results[0][1] == 1
            assert results[1][1] == 2

            # Search for "government" -- should match only beta's page
            results = conn.execute(
                """SELECT p.doc_id, p.page_number
                   FROM pages_fts
                   JOIN pages p ON p.id = pages_fts.rowid
                   WHERE pages_fts MATCH 'government'""",
            ).fetchall()
            assert len(results) == 1
            assert results[0][0] == "doc-beta"
            assert results[0][1] == 1

            # Search for something not present
            results = conn.execute(
                """SELECT p.doc_id FROM pages_fts
                   JOIN pages p ON p.id = pages_fts.rowid
                   WHERE pages_fts MATCH 'nonexistent'""",
            ).fetchall()
            assert len(results) == 0
            conn.close()

    def test_fts5_snippet_highlight(self):
        """Verify we can use FTS5 snippet/highlight functions for search UI."""
        from casestack.exporters.sqlite_export import SqliteExporter

        docs, pages = self._make_test_data()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            exporter = SqliteExporter()
            exporter.export(documents=docs, persons=[], db_path=db_path, pages=pages)

            conn = sqlite3.connect(str(db_path))
            results = conn.execute(
                """SELECT highlight(pages_fts, 0, '<b>', '</b>')
                   FROM pages_fts
                   WHERE pages_fts MATCH 'secrets'""",
            ).fetchall()
            assert len(results) == 1
            assert "<b>secrets</b>" in results[0][0]
            conn.close()

    def test_export_without_pages(self):
        """Exporter should still work if no pages are provided (backward compat)."""
        from casestack.exporters.sqlite_export import SqliteExporter

        docs = [
            Document(
                id="doc-legacy",
                title="Legacy Doc",
                source="local",
                category="other",
                ocrText="Some legacy text",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            exporter = SqliteExporter()
            exporter.export(documents=docs, persons=[], db_path=db_path)

            conn = sqlite3.connect(str(db_path))
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            page_count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            assert doc_count == 1
            assert page_count == 0

            # Check total_chars falls back to ocrText length
            row = conn.execute(
                "SELECT total_chars FROM documents WHERE doc_id = ?", ("doc-legacy",)
            ).fetchone()
            assert row[0] == len("Some legacy text")
            conn.close()


# ---------------------------------------------------------------------------
# Round-trip ingest test
# ---------------------------------------------------------------------------


class TestRoundTripIngest:
    def test_text_file_ingest_produces_pages(self):
        """Ingest text files -> SQLite -> verify pages table + FTS5 search."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            docs_dir = tmpdir / "docs"
            docs_dir.mkdir()
            ocr_dir = tmpdir / "ocr"
            ocr_dir.mkdir()

            # Create two text files with distinctive content
            (docs_dir / "contract.txt").write_text(
                "This contract governs the sale of property at 123 Main Street.",
                encoding="utf-8",
            )
            (docs_dir / "memo.txt").write_text(
                "Internal memorandum regarding quarterly financial performance review.",
                encoding="utf-8",
            )

            # Run the text ingest function
            from casestack.ingest import _ingest_text_files

            _ingest_text_files(docs_dir, ocr_dir)

            # Verify JSON files were created with pages
            json_files = sorted(ocr_dir.glob("*.json"))
            assert len(json_files) == 2

            documents = []
            all_pages = []
            for jf in json_files:
                result = ProcessingResult.model_validate_json(
                    jf.read_text(encoding="utf-8")
                )
                assert result.document is not None
                assert len(result.pages) == 1  # text files produce 1 page each
                documents.append(result.document)
                all_pages.extend(result.pages)

            assert len(all_pages) == 2

            # Export to SQLite
            from casestack.exporters.sqlite_export import SqliteExporter

            db_path = tmpdir / "test.db"
            exporter = SqliteExporter()
            exporter.export(
                documents=documents, persons=[], db_path=db_path, pages=all_pages
            )

            # Verify DB contents
            conn = sqlite3.connect(str(db_path))
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            page_count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            assert doc_count == 2
            assert page_count == 2

            # FTS5 search for "contract"
            results = conn.execute(
                """SELECT p.doc_id, p.page_number, p.text_content
                   FROM pages_fts
                   JOIN pages p ON p.id = pages_fts.rowid
                   WHERE pages_fts MATCH 'contract'""",
            ).fetchall()
            assert len(results) == 1
            assert "contract" in results[0][2].lower()
            assert results[0][1] == 1  # page_number

            # FTS5 search for "memorandum"
            results = conn.execute(
                """SELECT p.doc_id, p.page_number
                   FROM pages_fts
                   JOIN pages p ON p.id = pages_fts.rowid
                   WHERE pages_fts MATCH 'memorandum'""",
            ).fetchall()
            assert len(results) == 1
            assert results[0][1] == 1  # page_number

            # FTS5 search for "financial" with document join
            results = conn.execute(
                """SELECT d.title, p.page_number, p.text_content
                   FROM pages_fts
                   JOIN pages p ON p.id = pages_fts.rowid
                   JOIN documents d ON d.id = p.document_id
                   WHERE pages_fts MATCH 'financial'""",
            ).fetchall()
            assert len(results) == 1
            assert "Memo" in results[0][0]  # title derived from filename
            conn.close()

    def test_multi_page_document(self):
        """Verify a document with multiple pages has correct page numbers."""
        from casestack.exporters.sqlite_export import SqliteExporter

        doc = Document(
            id="doc-multipage",
            title="Multi-Page Report",
            source="fbi",
            category="investigation",
            ocrText="Page 1 content\n\nPage 2 content\n\nPage 3 content",
            pageCount=3,
        )
        pages = [
            Page(
                document_id="doc-multipage",
                page_number=i,
                text_content=f"Page {i} content with unique keywordx{i}x",
                char_count=40,
            )
            for i in range(1, 4)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            exporter = SqliteExporter()
            exporter.export(
                documents=[doc], persons=[], db_path=db_path, pages=pages
            )

            conn = sqlite3.connect(str(db_path))

            # Verify page count
            count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            assert count == 3

            # Search for page-specific keyword
            for i in range(1, 4):
                results = conn.execute(
                    """SELECT p.page_number
                       FROM pages_fts
                       JOIN pages p ON p.id = pages_fts.rowid
                       WHERE pages_fts MATCH ?""",
                    (f"keywordx{i}x",),
                ).fetchall()
                assert len(results) == 1
                assert results[0][0] == i

            # Verify total_pages on document
            row = conn.execute(
                "SELECT total_pages FROM documents WHERE doc_id = ?",
                ("doc-multipage",),
            ).fetchone()
            assert row[0] == 3
            conn.close()


# ---------------------------------------------------------------------------
# Docling page splitting tests
# ---------------------------------------------------------------------------


class TestDoclingPageSplitting:
    """Test the _split_docling_pages helper."""

    def test_form_feed_split(self):
        from casestack.processors.ocr import _split_docling_pages

        text = "Page one content\fPage two content\fPage three content"
        pages = _split_docling_pages(text, "doc1")
        assert len(pages) == 3
        assert pages[0].page_number == 1
        assert pages[1].page_number == 2
        assert pages[2].page_number == 3
        assert "one" in pages[0].text_content
        assert "three" in pages[2].text_content

    def test_section_break_split(self):
        from casestack.processors.ocr import _split_docling_pages

        # Create text with section breaks, each chunk > 200 chars
        chunk = "A" * 250
        text = f"{chunk}\n\n{chunk}\n\n{chunk}"
        pages = _split_docling_pages(text, "doc1")
        assert len(pages) == 3
        for p in pages:
            assert p.document_id == "doc1"

    def test_short_chunks_merged(self):
        from casestack.processors.ocr import _split_docling_pages

        # Short chunks should be merged together
        text = "Short.\n\nAlso short.\n\nStill short."
        pages = _split_docling_pages(text, "doc1")
        # All are under 200 chars, so they merge into 1 page
        assert len(pages) == 1
        assert "Short" in pages[0].text_content
        assert "Also short" in pages[0].text_content

    def test_empty_text_returns_single_page(self):
        from casestack.processors.ocr import _split_docling_pages

        pages = _split_docling_pages("", "doc1")
        assert len(pages) == 1
        assert pages[0].page_number == 1

    def test_mixed_long_short_chunks(self):
        from casestack.processors.ocr import _split_docling_pages

        long = "X" * 300
        text = f"{long}\n\nshort\n\n{long}"
        pages = _split_docling_pages(text, "doc1")
        # First long chunk -> page 1, "short" merges with second long -> page 2
        assert len(pages) == 2
