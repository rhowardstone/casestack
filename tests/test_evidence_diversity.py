"""Tests for evidence diversity: server-side query cap and per-doc evidence cap.

Two bugs found during dogfooding:
1. Query planner generates 7+ queries (violates Rule 6 2-5 limit), causing one
   large document to dominate results via RRF score accumulation.
2. Without a per-document cap, the OIG report (128 pages) fills all evidence
   slots and crowds out relevant pages from smaller documents like FBI FD-302s.
"""
from __future__ import annotations

import pytest

from casestack.api.routes.ask import (
    _MAX_PAGES_PER_DOC_IN_EVIDENCE,
    _cap_evidence_per_doc,
)


def _make_results(doc_pages: list[tuple[str, int]]) -> list[dict]:
    return [
        {
            "doc_id": doc_id,
            "title": f"Title for {doc_id}",
            "page_number": page,
            "text": f"Content of {doc_id} page {page}",
            "snippet": f"...snippet...",
        }
        for doc_id, page in doc_pages
    ]


class TestCapEvidencePerDoc:
    def test_empty_input(self):
        assert _cap_evidence_per_doc([]) == []

    def test_single_doc_within_limit(self):
        results = _make_results([("OIG", i) for i in range(3)])
        out = _cap_evidence_per_doc(results)
        assert len(out) == 3  # 3 ≤ _MAX_PAGES_PER_DOC_IN_EVIDENCE (4)

    def test_single_doc_exceeds_limit(self):
        """One large document should be capped."""
        results = _make_results([("OIG", i) for i in range(15)])
        out = _cap_evidence_per_doc(results)
        assert len(out) == _MAX_PAGES_PER_DOC_IN_EVIDENCE

    def test_rank_order_preserved(self):
        """Best-ranked pages (first in list) are kept, not last."""
        results = _make_results([("OIG", i) for i in range(10)])
        out = _cap_evidence_per_doc(results)
        kept_pages = [r["page_number"] for r in out]
        assert kept_pages == list(range(_MAX_PAGES_PER_DOC_IN_EVIDENCE))

    def test_multiple_docs_each_capped(self):
        """Each document is independently capped."""
        # 6 OIG pages + 6 FD302 pages
        results = _make_results(
            [("OIG", i) for i in range(6)] + [("FD302", i) for i in range(6)]
        )
        out = _cap_evidence_per_doc(results)
        oig_pages = [r for r in out if r["doc_id"] == "OIG"]
        fd302_pages = [r for r in out if r["doc_id"] == "FD302"]
        assert len(oig_pages) == _MAX_PAGES_PER_DOC_IN_EVIDENCE
        assert len(fd302_pages) == _MAX_PAGES_PER_DOC_IN_EVIDENCE

    def test_small_doc_not_truncated(self):
        """A 1-page document always passes through."""
        results = _make_results([("OIG", i) for i in range(15)] + [("FD302", 1)])
        out = _cap_evidence_per_doc(results)
        fd302_in_out = [r for r in out if r["doc_id"] == "FD302"]
        assert len(fd302_in_out) == 1

    def test_interleaved_docs_maintain_order(self):
        """Interleaved results (RRF order) are capped correctly."""
        # Simulate RRF output: OIG and FD302 interleaved
        pairs = []
        for i in range(5):
            pairs.append(("OIG", i))
            pairs.append(("FD302", i))
        results = _make_results(pairs)
        out = _cap_evidence_per_doc(results)
        # OIG capped at 4, FD302 capped at 4 → max 8 results
        assert len(out) <= 2 * _MAX_PAGES_PER_DOC_IN_EVIDENCE
        oig = [r for r in out if r["doc_id"] == "OIG"]
        fd = [r for r in out if r["doc_id"] == "FD302"]
        assert len(oig) == _MAX_PAGES_PER_DOC_IN_EVIDENCE
        assert len(fd) == _MAX_PAGES_PER_DOC_IN_EVIDENCE

    def test_diversity_prevents_single_doc_dominance(self):
        """Core regression: 15 OIG pages + 1 FD302 page → FD302 is included."""
        results = _make_results([("OIG", i) for i in range(15)] + [("FD302", 5)])
        out = _cap_evidence_per_doc(results)
        doc_ids = {r["doc_id"] for r in out}
        assert "FD302" in doc_ids, "Small document must not be crowded out by large document"
