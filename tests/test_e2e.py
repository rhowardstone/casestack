"""End-to-end integration test: ingest -> search -> ask -> pii.

Tests the full CaseStack pipeline using text file ingestion (no PDF/OCR
dependencies) against a temporary directory with realistic document content.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
import yaml

from casestack.case import CaseConfig
from casestack.ingest import run_ingest
from casestack.pii import scan_database, redact_database


@pytest.fixture
def e2e_case(tmp_path, monkeypatch):
    """Create a realistic test case with multiple documents.

    Changes the working directory to tmp_path so that CaseConfig's
    relative path properties (output_dir, data_dir, cache_dir, db_path)
    resolve inside the temporary directory.
    """
    monkeypatch.chdir(tmp_path)

    docs_dir = tmp_path / "documents"
    docs_dir.mkdir()

    # Document 1: Financial records with PII
    (docs_dir / "financial-records.txt").write_text(
        "Southern Trust Company\nAccount Statement Q3 2020\n"
        "Wire transfer to Deutsche Bank: $450,000\n"
        "Beneficiary: John Smith\n"
        "Account: 4291-8827-3344\n"
        "Contact: john.smith@example.com\n"
        "Phone: (212) 555-0147\n",
        encoding="utf-8",
    )

    # Document 2: Legal correspondence with PII
    (docs_dir / "legal-memo.txt").write_text(
        "MEMORANDUM\nTo: Legal Department\nFrom: Jane Doe, Esq.\n"
        "RE: Offshore account compliance review\n\n"
        "The wire transfers through Deutsche Bank require additional KYC review.\n"
        "Client Social Security Number: 123-45-6789\n"
        "Date of birth: March 15, 1970\n"
        "Address: 123 Main Street\n",
        encoding="utf-8",
    )

    # Document 3: Clean document (no PII)
    (docs_dir / "public-notice.txt").write_text(
        "PUBLIC NOTICE\n\n"
        "The Board of Directors hereby announces the quarterly meeting\n"
        "scheduled for January 15, 2025 at the corporate headquarters.\n"
        "All shareholders are invited to attend.\n",
        encoding="utf-8",
    )

    case = CaseConfig(
        name="E2E Test Case",
        slug="e2e-test",
        documents_dir=docs_dir,
    )

    return case


class TestE2EPipeline:
    """Full pipeline integration tests."""

    def test_ingest_creates_database(self, e2e_case):
        """Ingest should create a SQLite database with documents and pages."""
        db_path = run_ingest(e2e_case)
        assert db_path.exists()

        conn = sqlite3.connect(str(db_path))
        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        page_count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        conn.close()

        assert doc_count == 3
        assert page_count == 3  # One page per text file

    def test_fts5_search_works(self, e2e_case):
        """FTS5 search should return page-level results."""
        db_path = run_ingest(e2e_case)
        conn = sqlite3.connect(str(db_path))

        # Search for a term that appears in financial and legal docs
        results = conn.execute(
            """
            SELECT d.doc_id, p.page_number,
                   snippet(pages_fts, 0, '**', '**', '...', 32) as snippet
            FROM pages_fts
            JOIN pages p ON p.id = pages_fts.rowid
            JOIN documents d ON d.id = p.document_id
            WHERE pages_fts MATCH '"Deutsche Bank"'
            """,
        ).fetchall()
        conn.close()

        assert len(results) >= 1
        # Should match in financial and/or legal docs
        snippets = " ".join(r[2] for r in results)
        assert "Deutsche" in snippets or "Bank" in snippets

    def test_search_pages_function(self, e2e_case):
        """The ask module's search_pages should work on the ingested database."""
        from casestack.ask import search_pages

        db_path = run_ingest(e2e_case)
        results = search_pages(db_path, ['"wire transfer"'])

        assert len(results) >= 1
        assert any(
            "wire" in r["text"].lower() or "wire" in r.get("snippet", "").lower()
            for r in results
        )

    def test_search_returns_correct_structure(self, e2e_case):
        """search_pages results should have all expected fields."""
        from casestack.ask import search_pages

        db_path = run_ingest(e2e_case)
        results = search_pages(db_path, ["Deutsche"])

        assert len(results) >= 1
        r = results[0]
        assert "doc_id" in r
        assert "title" in r
        assert "page_number" in r
        assert "text" in r
        assert "snippet" in r

    def test_pii_scan_detects_known_pii(self, e2e_case):
        """PII scanner should find email, phone, SSN in test documents."""
        db_path = run_ingest(e2e_case)
        result = scan_database(db_path)

        types_found = result.by_type
        # Should detect at least email and phone
        assert "email" in types_found or "phone" in types_found
        # Should also detect SSN from the legal memo
        assert "ssn" in types_found

    def test_pii_scan_reports_correct_page_count(self, e2e_case):
        """PII scan should report scanning all 3 pages."""
        db_path = run_ingest(e2e_case)
        result = scan_database(db_path)
        assert result.total_pages_scanned == 3

    def test_pii_redaction_removes_pii(self, e2e_case):
        """Redaction should remove PII from the database."""
        db_path = run_ingest(e2e_case)

        # Scan
        result = scan_database(db_path)
        original_matches = result.match_count

        assert original_matches > 0, "Expected PII matches in test documents"

        # Redact
        redacted_count = redact_database(db_path, result.matches)
        assert redacted_count > 0

        # Verify PII is reduced or gone
        result2 = scan_database(db_path)
        assert result2.match_count < original_matches

    def test_pii_redaction_uses_empty_strings(self, e2e_case):
        """Redaction replaces PII with empty strings, not [REDACTED] tags."""
        db_path = run_ingest(e2e_case)

        result = scan_database(db_path)
        emails = [m for m in result.matches if m.pattern_type == "email"]

        if emails:
            redact_database(db_path, emails)

            conn = sqlite3.connect(str(db_path))
            rows = conn.execute("SELECT text_content FROM pages").fetchall()
            conn.close()

            all_text = " ".join(r[0] for r in rows)
            assert "john.smith@example.com" not in all_text
            assert "[REDACTED]" not in all_text

    def test_datasette_config_generated(self, e2e_case):
        """Ingest should generate a datasette.yaml config."""
        run_ingest(e2e_case)
        config_path = e2e_case.output_dir / "datasette.yaml"
        assert config_path.exists()

        config = yaml.safe_load(config_path.read_text())
        assert "databases" in config
        assert "settings" in config

    def test_datasette_config_has_case_slug(self, e2e_case):
        """Datasette config should reference the case slug as database name."""
        run_ingest(e2e_case)
        config_path = e2e_case.output_dir / "datasette.yaml"
        config = yaml.safe_load(config_path.read_text())

        assert e2e_case.slug in config["databases"]
        db_config = config["databases"][e2e_case.slug]
        assert "tables" in db_config
        assert "documents" in db_config["tables"]
        assert "pages" in db_config["tables"]

    def test_output_directory_structure(self, e2e_case):
        """Ingest should create the expected output directory structure."""
        db_path = run_ingest(e2e_case)

        # Output dir should exist and contain the database
        assert e2e_case.output_dir.exists()
        assert db_path.parent == e2e_case.output_dir

        # OCR intermediate directory should exist
        ocr_dir = e2e_case.output_dir / "ocr"
        assert ocr_dir.exists()

        # JSON files from text ingestion should be in the ocr dir
        json_files = list(ocr_dir.glob("*.json"))
        assert len(json_files) == 3

    def test_cross_document_search(self, e2e_case):
        """A query matching content in multiple documents returns results from each."""
        from casestack.ask import search_pages

        db_path = run_ingest(e2e_case)

        # "Deutsche Bank" appears in both financial-records.txt and legal-memo.txt
        results = search_pages(db_path, ['"Deutsche Bank"'])
        doc_ids = {r["doc_id"] for r in results}
        assert len(doc_ids) >= 2, (
            f"Expected matches in at least 2 documents, got {doc_ids}"
        )

    def test_clean_document_has_no_pii(self, e2e_case):
        """The public notice document should have zero PII matches."""
        db_path = run_ingest(e2e_case)
        result = scan_database(db_path)

        # Find the doc_id for the public notice by looking at the DB
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT doc_id, title FROM documents WHERE title LIKE '%Public%'"
        ).fetchall()
        conn.close()

        assert len(rows) >= 1, "Public notice document should exist"
        public_doc_id = rows[0][0]

        # No PII matches should be for the public notice
        public_matches = [
            m for m in result.matches if m.doc_id == public_doc_id
        ]
        assert len(public_matches) == 0, (
            f"Public notice should have no PII, found: {public_matches}"
        )


class TestPresetLoading:
    """Test that preset YAML files load correctly into CaseConfig."""

    def test_epstein_preset_loads(self):
        """The epstein.yaml preset should parse into a valid CaseConfig."""
        preset_path = Path(__file__).parent.parent / "presets" / "epstein.yaml"
        if not preset_path.exists():
            pytest.skip("epstein.yaml preset not found")

        case = CaseConfig.from_yaml(preset_path)
        assert case.name == "Epstein Files Transparency Act"
        assert case.slug == "epstein"
        assert case.ocr_backend == "both"
        assert case.ocr_workers == 8
        assert "PERSON" in case.entity_types
        assert case.dedup_threshold == 0.90
        assert case.serve_port == 8001
        assert case.ask_proxy_enabled is True

    def test_quickstart_preset_loads(self):
        """The quickstart.yaml preset should parse into a valid CaseConfig."""
        preset_path = Path(__file__).parent.parent / "presets" / "quickstart.yaml"
        if not preset_path.exists():
            pytest.skip("quickstart.yaml preset not found")

        case = CaseConfig.from_yaml(preset_path)
        assert case.name == "My Document Collection"
        assert case.slug == "my-docs"
        assert case.ocr_backend == "pymupdf"
        assert case.ocr_workers == 4
        assert case.serve_port == 8001
