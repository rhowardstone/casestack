"""Tests for PII detection and redaction.

Covers:
- Tier 1 patterns: phone, email, SSN detection
- False positive filtering for SSN and phone patterns
- Tier 2 patterns: DOB (context-dependent), address detection
- Full database scan
- Redaction: empty string replacement, char_count update, FTS rebuild
- PIIScanResult properties (match_count, affected_pages, by_type)
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from casestack.pii import (
    ADDRESS_RE,
    DATE_RE,
    DOB_KEYWORDS,
    EMAIL_RE,
    PHONE_RE,
    SSN_RE,
    PIIMatch,
    PIIScanResult,
    _is_false_positive_phone,
    _is_false_positive_ssn,
    _scan_tier2,
    redact_database,
    scan_database,
)


# ---------------------------------------------------------------------------
# Helper: create a test database matching the CaseStack schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT UNIQUE,
    title TEXT,
    date TEXT,
    source TEXT,
    category TEXT,
    summary TEXT,
    total_pages INTEGER,
    total_chars INTEGER,
    file_path TEXT,
    tags TEXT
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER REFERENCES documents(id),
    doc_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    text_content TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    UNIQUE(doc_id, page_number)
);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    text_content,
    content='pages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, text_content) VALUES (new.id, new.text_content);
END;

CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, text_content)
        VALUES ('delete', old.id, old.text_content);
END;

CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, text_content)
        VALUES ('delete', old.id, old.text_content);
    INSERT INTO pages_fts(rowid, text_content)
        VALUES (new.id, new.text_content);
END;
"""


def _create_test_db(pages: list[tuple[str, int, str]]) -> Path:
    """Create a temp database with the given pages.

    Parameters
    ----------
    pages:
        List of (doc_id, page_number, text_content) tuples.

    Returns
    -------
    Path to the temporary database file.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = Path(tmp.name)
    tmp.close()

    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA_SQL)

    # Insert a document row for each unique doc_id
    seen_docs: set[str] = set()
    for doc_id, _, _ in pages:
        if doc_id not in seen_docs:
            conn.execute(
                "INSERT INTO documents (doc_id, title, source, category)"
                " VALUES (?, ?, 'test', 'test')",
                (doc_id, f"Test doc {doc_id}"),
            )
            seen_docs.add(doc_id)

    # Insert pages
    for doc_id, page_num, text in pages:
        doc_row_id = conn.execute(
            "SELECT id FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO pages (document_id, doc_id, page_number, text_content, char_count)"
            " VALUES (?, ?, ?, ?, ?)",
            (doc_row_id, doc_id, page_num, text, len(text)),
        )

    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Tier 1: Phone detection
# ---------------------------------------------------------------------------


class TestPhoneDetection:
    def test_standard_format(self):
        assert PHONE_RE.search("Call (212) 555-1234 today")

    def test_dashes_format(self):
        assert PHONE_RE.search("Phone: 212-555-1234")

    def test_dots_format(self):
        assert PHONE_RE.search("212.555.1234 is the number")

    def test_with_country_code(self):
        assert PHONE_RE.search("Call +1-212-555-1234")

    def test_no_match_short_number(self):
        assert PHONE_RE.search("555-1234") is None

    def test_no_match_random_digits(self):
        # Area codes starting with 0 or 1 are invalid
        assert PHONE_RE.search("012-345-6789") is None


class TestPhoneFalsePositives:
    def test_all_same_digit(self):
        assert _is_false_positive_phone("222-222-2222", "text 222-222-2222 text", 5)

    def test_sequential_digits(self):
        assert _is_false_positive_phone("234-567-8901", "text 234-567-8901 text", 5)

    def test_inside_url(self):
        text = "see https://example.com/2125551234 for details"
        assert _is_false_positive_phone("212-555-1234", text, 24)

    def test_near_bates_stamp(self):
        text = "Document EFTA00012345 page 212-555-1234"
        assert _is_false_positive_phone("212-555-1234", text, 27)

    def test_legitimate_phone_not_flagged(self):
        text = "Contact person at 212-555-1234 for info"
        assert not _is_false_positive_phone("212-555-1234", text, 18)


# ---------------------------------------------------------------------------
# Tier 1: Email detection
# ---------------------------------------------------------------------------


class TestEmailDetection:
    def test_standard_email(self):
        assert EMAIL_RE.search("Email: john.doe@example.com")

    def test_email_with_plus(self):
        assert EMAIL_RE.search("user+tag@gmail.com is valid")

    def test_email_with_subdomain(self):
        assert EMAIL_RE.search("admin@mail.company.co.uk")

    def test_no_match_without_tld(self):
        assert EMAIL_RE.search("not-an-email@localhost") is None

    def test_no_match_bare_at(self):
        assert EMAIL_RE.search("@ is an at sign") is None


# ---------------------------------------------------------------------------
# Tier 1: SSN detection
# ---------------------------------------------------------------------------


class TestSSNDetection:
    def test_standard_format(self):
        assert SSN_RE.search("SSN: 123-45-6789")

    def test_no_dashes(self):
        assert SSN_RE.search("SSN: 123456789")

    def test_with_spaces(self):
        assert SSN_RE.search("SSN: 123 45 6789")


class TestSSNFalsePositives:
    def test_all_same_digit(self):
        assert _is_false_positive_ssn("111-11-1111", "text 111-11-1111 text", 5)

    def test_prefix_000(self):
        assert _is_false_positive_ssn("000-12-3456", "text 000-12-3456 text", 5)

    def test_prefix_666(self):
        assert _is_false_positive_ssn("666-12-3456", "text 666-12-3456 text", 5)

    def test_prefix_9xx(self):
        assert _is_false_positive_ssn("900-12-3456", "text 900-12-3456 text", 5)

    def test_middle_group_zeros(self):
        assert _is_false_positive_ssn("123-00-6789", "text 123-00-6789 text", 5)

    def test_last_group_zeros(self):
        assert _is_false_positive_ssn("123-45-0000", "text 123-45-0000 text", 5)

    def test_inside_url(self):
        text = "see https://example.com/123-45-6789 for details"
        assert _is_false_positive_ssn("123-45-6789", text, 24)

    def test_near_efta_document_id(self):
        text = "EFTA00012345 reference 123-45-6789"
        assert _is_false_positive_ssn("123-45-6789", text, 23)

    def test_legitimate_ssn_not_flagged(self):
        text = "The individual's SSN is 123-45-6789 as recorded"
        assert not _is_false_positive_ssn("123-45-6789", text, 24)


# ---------------------------------------------------------------------------
# Tier 2: DOB detection (context-dependent)
# ---------------------------------------------------------------------------


class TestDOBDetection:
    def test_date_near_birth_keyword(self):
        result = PIIScanResult(total_pages_scanned=1)
        text = "John was born on 03/15/1985 in New York."
        _scan_tier2(text, "doc-1", 1, result)
        dob_matches = [m for m in result.matches if m.pattern_type == "dob"]
        assert len(dob_matches) == 1
        assert dob_matches[0].match_text == "03/15/1985"
        assert dob_matches[0].confidence == 0.75

    def test_date_near_dob_keyword(self):
        result = PIIScanResult(total_pages_scanned=1)
        text = "DOB: 12/25/1990, lives in LA."
        _scan_tier2(text, "doc-1", 1, result)
        dob_matches = [m for m in result.matches if m.pattern_type == "dob"]
        assert len(dob_matches) == 1

    def test_date_near_birthday_keyword(self):
        result = PIIScanResult(total_pages_scanned=1)
        text = "Her birthday is January 5, 1992 and she likes cake."
        _scan_tier2(text, "doc-1", 1, result)
        dob_matches = [m for m in result.matches if m.pattern_type == "dob"]
        assert len(dob_matches) == 1

    def test_date_without_context_not_flagged(self):
        result = PIIScanResult(total_pages_scanned=1)
        text = "The meeting is scheduled for 03/15/2024 in the boardroom."
        _scan_tier2(text, "doc-1", 1, result)
        dob_matches = [m for m in result.matches if m.pattern_type == "dob"]
        assert len(dob_matches) == 0


# ---------------------------------------------------------------------------
# Tier 2: Address detection
# ---------------------------------------------------------------------------


class TestAddressDetection:
    def test_standard_street(self):
        assert ADDRESS_RE.search("Located at 123 Main Street")

    def test_avenue(self):
        assert ADDRESS_RE.search("Office at 456 Park Ave")

    def test_boulevard(self):
        assert ADDRESS_RE.search("Lives at 789 Sunset Blvd")

    def test_drive(self):
        assert ADDRESS_RE.search("Found at 12 Oak Tree Dr")

    def test_road(self):
        assert ADDRESS_RE.search("Located at 55 Elm Rd")

    def test_no_match_without_street_type(self):
        # Just a number followed by words, no street type
        assert ADDRESS_RE.search("We have 123 red balloons") is None

    def test_address_in_tier2_scan(self):
        result = PIIScanResult(total_pages_scanned=1)
        text = "The witness lives at 742 Evergreen Terrace Rd near the school."
        _scan_tier2(text, "doc-1", 1, result)
        addr_matches = [m for m in result.matches if m.pattern_type == "address"]
        assert len(addr_matches) == 1
        assert addr_matches[0].confidence == 0.7


# ---------------------------------------------------------------------------
# PIIScanResult properties
# ---------------------------------------------------------------------------


class TestPIIScanResult:
    def test_match_count(self):
        result = PIIScanResult(total_pages_scanned=10)
        result.matches.append(
            PIIMatch("d1", 1, "test@example.com", "email", 0.95, 0, 16)
        )
        result.matches.append(
            PIIMatch("d1", 1, "212-555-1234", "phone", 0.9, 20, 32)
        )
        assert result.match_count == 2

    def test_affected_pages(self):
        result = PIIScanResult(total_pages_scanned=10)
        result.matches.append(
            PIIMatch("d1", 1, "test@example.com", "email", 0.95, 0, 16)
        )
        result.matches.append(
            PIIMatch("d1", 1, "212-555-1234", "phone", 0.9, 20, 32)
        )
        result.matches.append(
            PIIMatch("d2", 3, "jane@test.org", "email", 0.95, 0, 13)
        )
        # Two unique (doc_id, page_number) pairs: (d1, 1) and (d2, 3)
        assert result.affected_pages == 2

    def test_by_type(self):
        result = PIIScanResult(total_pages_scanned=5)
        result.matches.append(
            PIIMatch("d1", 1, "a@b.com", "email", 0.95, 0, 7)
        )
        result.matches.append(
            PIIMatch("d1", 2, "c@d.com", "email", 0.95, 0, 7)
        )
        result.matches.append(
            PIIMatch("d1", 1, "212-555-1234", "phone", 0.9, 10, 22)
        )
        assert result.by_type == {"email": 2, "phone": 1}

    def test_empty_result(self):
        result = PIIScanResult(total_pages_scanned=0)
        assert result.match_count == 0
        assert result.affected_pages == 0
        assert result.by_type == {}


# ---------------------------------------------------------------------------
# Full database scan
# ---------------------------------------------------------------------------


class TestScanDatabase:
    def test_scan_finds_email(self):
        db = _create_test_db([
            ("doc-1", 1, "Contact john.doe@example.com for details."),
        ])
        try:
            result = scan_database(db)
            assert result.total_pages_scanned == 1
            emails = [m for m in result.matches if m.pattern_type == "email"]
            assert len(emails) == 1
            assert emails[0].match_text == "john.doe@example.com"
            assert emails[0].doc_id == "doc-1"
            assert emails[0].page_number == 1
        finally:
            db.unlink(missing_ok=True)

    def test_scan_finds_phone(self):
        db = _create_test_db([
            ("doc-1", 1, "Call us at (212) 555-1234 for help."),
        ])
        try:
            result = scan_database(db)
            phones = [m for m in result.matches if m.pattern_type == "phone"]
            assert len(phones) == 1
            assert "555-1234" in phones[0].match_text
        finally:
            db.unlink(missing_ok=True)

    def test_scan_finds_ssn(self):
        db = _create_test_db([
            ("doc-1", 1, "SSN on file: 123-45-6789 verified."),
        ])
        try:
            result = scan_database(db)
            ssns = [m for m in result.matches if m.pattern_type == "ssn"]
            assert len(ssns) == 1
            assert ssns[0].match_text == "123-45-6789"
        finally:
            db.unlink(missing_ok=True)

    def test_scan_filters_invalid_ssn(self):
        db = _create_test_db([
            ("doc-1", 1, "Reference: 000-12-3456 is not a real SSN."),
        ])
        try:
            result = scan_database(db)
            ssns = [m for m in result.matches if m.pattern_type == "ssn"]
            assert len(ssns) == 0
        finally:
            db.unlink(missing_ok=True)

    def test_scan_finds_dob_with_context(self):
        db = _create_test_db([
            ("doc-1", 1, "Subject was born on 03/15/1985 in NYC."),
        ])
        try:
            result = scan_database(db)
            dobs = [m for m in result.matches if m.pattern_type == "dob"]
            assert len(dobs) == 1
            assert dobs[0].match_text == "03/15/1985"
        finally:
            db.unlink(missing_ok=True)

    def test_scan_finds_address(self):
        db = _create_test_db([
            ("doc-1", 1, "Witness resides at 742 Evergreen Terrace Rd in Springfield."),
        ])
        try:
            result = scan_database(db)
            addrs = [m for m in result.matches if m.pattern_type == "address"]
            assert len(addrs) == 1
        finally:
            db.unlink(missing_ok=True)

    def test_scan_multiple_pages_multiple_docs(self):
        db = _create_test_db([
            ("doc-1", 1, "Email: alice@example.com"),
            ("doc-1", 2, "Phone: (312) 555-7890"),
            ("doc-2", 1, "SSN: 234-56-7890 is recorded here."),
        ])
        try:
            result = scan_database(db)
            assert result.total_pages_scanned == 3
            assert result.match_count >= 3
            assert result.affected_pages >= 3
        finally:
            db.unlink(missing_ok=True)

    def test_scan_empty_text_skipped(self):
        db = _create_test_db([
            ("doc-1", 1, ""),
        ])
        try:
            result = scan_database(db)
            assert result.total_pages_scanned == 1
            assert result.match_count == 0
        finally:
            db.unlink(missing_ok=True)

    def test_scan_no_pii_clean_document(self):
        db = _create_test_db([
            ("doc-1", 1, "This is a clean document with no personal information."),
        ])
        try:
            result = scan_database(db)
            assert result.match_count == 0
        finally:
            db.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


class TestRedactDatabase:
    def test_redact_replaces_with_empty_string(self):
        db = _create_test_db([
            ("doc-1", 1, "Contact john@example.com for info."),
        ])
        try:
            result = scan_database(db)
            assert result.match_count >= 1
            emails = [m for m in result.matches if m.pattern_type == "email"]

            count = redact_database(db, emails)
            assert count == 1

            # Verify the email is gone
            conn = sqlite3.connect(str(db))
            text = conn.execute(
                "SELECT text_content FROM pages WHERE doc_id = ? AND page_number = ?",
                ("doc-1", 1),
            ).fetchone()[0]
            conn.close()

            assert "john@example.com" not in text
            # The replacement is empty string, not [REDACTED]
            assert "[REDACTED]" not in text
            assert text == "Contact  for info."
        finally:
            db.unlink(missing_ok=True)

    def test_redact_updates_char_count(self):
        original_text = "SSN on file: 123-45-6789 verified."
        db = _create_test_db([
            ("doc-1", 1, original_text),
        ])
        try:
            result = scan_database(db)
            ssns = [m for m in result.matches if m.pattern_type == "ssn"]
            assert len(ssns) == 1

            redact_database(db, ssns)

            conn = sqlite3.connect(str(db))
            row = conn.execute(
                "SELECT text_content, char_count FROM pages WHERE doc_id = ? AND page_number = ?",
                ("doc-1", 1),
            ).fetchone()
            conn.close()

            text = row[0]
            char_count = row[1]
            assert "123-45-6789" not in text
            assert char_count == len(text)
            assert char_count < len(original_text)
        finally:
            db.unlink(missing_ok=True)

    def test_redact_rebuilds_fts(self):
        db = _create_test_db([
            ("doc-1", 1, "Email: secret@hidden.org is confidential."),
        ])
        try:
            # Verify FTS finds the email text before redaction
            conn = sqlite3.connect(str(db))
            before = conn.execute(
                "SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH 'secret'",
            ).fetchone()[0]
            conn.close()
            assert before >= 1

            result = scan_database(db)
            emails = [m for m in result.matches if m.pattern_type == "email"]
            redact_database(db, emails)

            # After redaction + rebuild, FTS should no longer find 'secret'
            conn = sqlite3.connect(str(db))
            after = conn.execute(
                "SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH 'secret'",
            ).fetchone()[0]
            conn.close()
            assert after == 0
        finally:
            db.unlink(missing_ok=True)

    def test_redact_multiple_matches_same_page(self):
        text = "Email: a@b.com, Phone: (312) 555-7890, SSN: 234-56-7890"
        db = _create_test_db([
            ("doc-1", 1, text),
        ])
        try:
            result = scan_database(db)
            # Should have at least email + phone + ssn
            assert result.match_count >= 3

            count = redact_database(db, result.matches)
            assert count >= 3

            conn = sqlite3.connect(str(db))
            row = conn.execute(
                "SELECT text_content, char_count FROM pages WHERE doc_id = ? AND page_number = ?",
                ("doc-1", 1),
            ).fetchone()
            conn.close()

            redacted_text = row[0]
            assert "a@b.com" not in redacted_text
            assert "555-7890" not in redacted_text
            assert "234-56-7890" not in redacted_text
            assert row[1] == len(redacted_text)
        finally:
            db.unlink(missing_ok=True)

    def test_redact_empty_matches_returns_zero(self):
        db = _create_test_db([
            ("doc-1", 1, "Clean text."),
        ])
        try:
            count = redact_database(db, [])
            assert count == 0
        finally:
            db.unlink(missing_ok=True)

    def test_redact_nonexistent_page_skipped(self):
        db = _create_test_db([
            ("doc-1", 1, "Some text."),
        ])
        try:
            fake_match = PIIMatch(
                doc_id="doc-nonexistent",
                page_number=99,
                match_text="fake",
                pattern_type="email",
                confidence=0.95,
                start=0,
                end=4,
            )
            count = redact_database(db, [fake_match])
            assert count == 0
        finally:
            db.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# CLI integration smoke test
# ---------------------------------------------------------------------------


class TestCLICommands:
    def test_scan_pii_command_exists(self):
        """Verify the scan-pii CLI command is registered."""
        from click.testing import CliRunner

        from casestack.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["scan-pii", "--help"])
        assert result.exit_code == 0
        assert "Scan the database" in result.output

    def test_redact_command_exists(self):
        """Verify the redact CLI command is registered."""
        from click.testing import CliRunner

        from casestack.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["redact", "--help"])
        assert result.exit_code == 0
        assert "Redact PII" in result.output
        assert "--dry-run" in result.output
