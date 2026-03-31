"""Regression tests for _dedupe_sources() in the ask API route.

Previously the ask endpoint emitted one source chip per (doc_id, page) pair,
producing 40+ chips for a single answer. These tests enforce the corrected
behaviour: one chip per unique document, capped at _MAX_SOURCE_DOCS.
"""
from __future__ import annotations

import pytest

from casestack.api.routes.ask import _MAX_SOURCE_DOCS, _dedupe_sources


def _make_results(doc_pages: list[tuple[str, int]]) -> list[dict]:
    """Build a minimal search results list from (doc_id, page_number) pairs."""
    return [
        {"doc_id": doc_id, "title": f"Title for {doc_id}", "page_number": page}
        for doc_id, page in doc_pages
    ]


class TestDedupeSources:
    def test_empty_input(self):
        assert _dedupe_sources([]) == []

    def test_single_result(self):
        results = _make_results([("DOC-001", 1)])
        out = _dedupe_sources(results)
        assert len(out) == 1
        assert out[0]["doc_id"] == "DOC-001"
        assert out[0]["page"] == 1

    def test_same_doc_multiple_pages_collapsed(self):
        """Bug regression: 40 rows from same doc → 1 chip."""
        results = _make_results([("DOC-001", p) for p in range(1, 41)])
        out = _dedupe_sources(results)
        assert len(out) == 1
        assert out[0]["doc_id"] == "DOC-001"

    def test_keeps_first_seen_page(self):
        """The chip should show the FIRST occurrence's page (best FTS5 rank).

        Regression: previously kept lowest page number, which navigated to
        cover pages (page 4) instead of the relevant content (page 89+).
        FTS5 returns results ordered by rank, so first-seen = best match.
        """
        results = _make_results([
            ("DOC-001", 89),  # best-ranked hit — on the relevant page
            ("DOC-001", 4),   # lower page but worse rank — was a cover hit
            ("DOC-001", 42),
        ])
        out = _dedupe_sources(results)
        assert out[0]["page"] == 89  # must use best-rank page, not minimum

    def test_multiple_docs_one_chip_each(self):
        results = _make_results([
            ("DOC-001", 1), ("DOC-001", 5),
            ("DOC-002", 2), ("DOC-002", 8),
            ("DOC-003", 1),
        ])
        out = _dedupe_sources(results)
        doc_ids = [r["doc_id"] for r in out]
        assert len(doc_ids) == 3
        assert set(doc_ids) == {"DOC-001", "DOC-002", "DOC-003"}

    def test_capped_at_max(self):
        """More than _MAX_SOURCE_DOCS distinct documents must be capped."""
        results = _make_results([(f"DOC-{i:03d}", 1) for i in range(_MAX_SOURCE_DOCS + 10)])
        out = _dedupe_sources(results)
        assert len(out) == _MAX_SOURCE_DOCS

    def test_exactly_at_cap_not_truncated(self):
        results = _make_results([(f"DOC-{i:03d}", 1) for i in range(_MAX_SOURCE_DOCS)])
        out = _dedupe_sources(results)
        assert len(out) == _MAX_SOURCE_DOCS

    def test_output_has_required_keys(self):
        results = _make_results([("DOC-001", 3)])
        out = _dedupe_sources(results)
        assert "doc_id" in out[0]
        assert "title" in out[0]
        assert "page" in out[0]

    def test_title_preserved(self):
        results = [{"doc_id": "DOC-001", "title": "Important Filing", "page_number": 1}]
        out = _dedupe_sources(results)
        assert out[0]["title"] == "Important Filing"

    def test_ordering_preserved(self):
        """Output order should reflect input order (FTS5 rank order)."""
        results = _make_results([("DOC-C", 1), ("DOC-A", 1), ("DOC-B", 1)])
        out = _dedupe_sources(results)
        assert [r["doc_id"] for r in out] == ["DOC-C", "DOC-A", "DOC-B"]
