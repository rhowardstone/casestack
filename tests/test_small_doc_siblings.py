"""Tests for _inject_small_doc_siblings.

When a query matches page 1 of a 3-page government letter, pages 2-3 contain
critical evidence (e.g., specific timestamps in a discovery letter) that won't
rank on their own.  For documents with ≤_SMALL_DOC_MAX_PAGES pages, all pages
are injected so the LLM sees the complete document.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from casestack.api.routes.ask import _SMALL_DOC_MAX_PAGES, _inject_small_doc_siblings


def _make_db(pages_by_doc: dict[str, list[str]]) -> sqlite3.Connection:
    """Build an in-memory DB with documents + pages tables."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE documents (id INTEGER PRIMARY KEY, doc_id TEXT UNIQUE, title TEXT)"
    )
    conn.execute(
        "CREATE TABLE pages (id INTEGER PRIMARY KEY, doc_id TEXT, page_number INTEGER,"
        " document_id INTEGER, text_content TEXT)"
    )
    doc_id_num = 1
    page_id_num = 1
    for doc_id, page_texts in pages_by_doc.items():
        conn.execute(
            "INSERT INTO documents (id, doc_id, title) VALUES (?, ?, ?)",
            (doc_id_num, doc_id, f"Title {doc_id}"),
        )
        for i, text in enumerate(page_texts, start=1):
            conn.execute(
                "INSERT INTO pages (id, doc_id, page_number, document_id, text_content)"
                " VALUES (?, ?, ?, ?, ?)",
                (page_id_num, doc_id, i, doc_id_num, text),
            )
            page_id_num += 1
        doc_id_num += 1
    conn.commit()
    return conn


class TestInjectSmallDocSiblings:
    def _result(self, doc_id: str, page: int) -> dict:
        return {"doc_id": doc_id, "title": f"Title {doc_id}", "page_number": page, "text": "t", "snippet": "s"}

    def test_no_results_no_injection(self):
        conn = _make_db({"DOC": ["p1", "p2"]})
        results = []
        seen: set = set()
        _inject_small_doc_siblings(conn, results, seen)
        assert results == []

    def test_small_doc_siblings_injected(self):
        """3-page doc: if page 1 matches, inject pages 2+3."""
        conn = _make_db({"DOC": ["page one text", "page two text", "page three text"]})
        results = [self._result("DOC", 1)]
        seen = {("DOC", 1)}
        _inject_small_doc_siblings(conn, results, seen)
        pages = sorted(r["page_number"] for r in results)
        assert pages == [1, 2, 3]

    def test_large_doc_not_expanded(self):
        """Document with _SMALL_DOC_MAX_PAGES+1 pages must not be expanded."""
        pages = {f"p{i}": f"text {i}" for i in range(1, _SMALL_DOC_MAX_PAGES + 2)}
        conn = _make_db({"BIG": list(pages.values())})
        results = [self._result("BIG", 1)]
        seen = {("BIG", 1)}
        _inject_small_doc_siblings(conn, results, seen)
        assert len(results) == 1  # no siblings added

    def test_exactly_max_pages_expanded(self):
        """Document with exactly _SMALL_DOC_MAX_PAGES pages IS expanded."""
        page_texts = [f"text {i}" for i in range(_SMALL_DOC_MAX_PAGES)]
        conn = _make_db({"SMALL": page_texts})
        results = [self._result("SMALL", 1)]
        seen = {("SMALL", 1)}
        _inject_small_doc_siblings(conn, results, seen)
        assert len(results) == _SMALL_DOC_MAX_PAGES

    def test_already_seen_pages_not_duplicated(self):
        """Pages already in results are not added again."""
        conn = _make_db({"DOC": ["p1", "p2", "p3"]})
        results = [self._result("DOC", 1), self._result("DOC", 2)]
        seen = {("DOC", 1), ("DOC", 2)}
        _inject_small_doc_siblings(conn, results, seen)
        pages = sorted(r["page_number"] for r in results)
        assert pages == [1, 2, 3]  # only page 3 added

    def test_multiple_small_docs_both_expanded(self):
        """Two small documents are both fully expanded."""
        conn = _make_db({
            "LETTER": ["l1", "l2", "l3"],
            "NOTE": ["n1", "n2"],
        })
        results = [self._result("LETTER", 1), self._result("NOTE", 1)]
        seen = {("LETTER", 1), ("NOTE", 1)}
        _inject_small_doc_siblings(conn, results, seen)
        letter_pages = [r["page_number"] for r in results if r["doc_id"] == "LETTER"]
        note_pages = [r["page_number"] for r in results if r["doc_id"] == "NOTE"]
        assert sorted(letter_pages) == [1, 2, 3]
        assert sorted(note_pages) == [1, 2]

    def test_seen_set_updated(self):
        """The seen set must be updated to prevent duplicates in later processing."""
        conn = _make_db({"DOC": ["p1", "p2", "p3"]})
        results = [self._result("DOC", 1)]
        seen = {("DOC", 1)}
        _inject_small_doc_siblings(conn, results, seen)
        assert ("DOC", 2) in seen
        assert ("DOC", 3) in seen

    def test_six_page_doc_expanded(self):
        """Regression: 6-page FD-302 interview (e.g. Captain's August 10 interview) must be
        fully expanded.  Threshold raised from 5 to 6 after p5 of EFTA00039972 (containing
        'gathered records' / 'could not locate inmate file') was missed when p4 matched."""
        page_texts = [f"text {i}" for i in range(_SMALL_DOC_MAX_PAGES)]
        conn = _make_db({"FD302": page_texts})
        results = [self._result("FD302", 1)]
        seen = {("FD302", 1)}
        _inject_small_doc_siblings(conn, results, seen)
        assert len(results) == _SMALL_DOC_MAX_PAGES
