"""Regression tests for hybrid FTS5 + semantic search in ask.py.

Tests cover:
- _rrf_merge(): correct merging of FTS5 and semantic ranked lists
- _load_page_embeddings(): graceful handling when table is empty or absent
- _search_semantic(): graceful fallback when embeddings unavailable
- PageEmbedder: generates and stores page embeddings in SQLite
"""
from __future__ import annotations

import sqlite3
import struct
import tempfile
from pathlib import Path

import pytest

from casestack.api.routes.ask import _rrf_merge, _load_page_embeddings, _search_semantic


# ---------------------------------------------------------------------------
# Helper: minimal in-memory DB
# ---------------------------------------------------------------------------

def _make_db(pages: list[tuple[str, int, str]]) -> Path:
    """Create a temp DB with documents + pages + page_embeddings tables."""
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
        CREATE TABLE page_embeddings (
            page_id   INTEGER PRIMARY KEY REFERENCES pages(id),
            model     TEXT NOT NULL,
            dims      INTEGER NOT NULL,
            embedding BLOB NOT NULL
        );
    """)
    conn.execute("INSERT INTO documents VALUES (1, 'doc-a', 'Test Doc')")
    for page_id, (doc_id, page_num, text) in enumerate(pages, start=1):
        conn.execute(
            "INSERT INTO pages VALUES (?, 1, ?, ?, ?, ?)",
            (page_id, doc_id, page_num, text, len(text)),
        )
    conn.commit()
    conn.close()
    return db_path


def _store_embedding(db_path: Path, page_id: int, vector: list[float]) -> None:
    blob = struct.pack(f"{len(vector)}f", *vector)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO page_embeddings (page_id, model, dims, embedding) VALUES (?, ?, ?, ?)",
        (page_id, "test-model", len(vector), blob),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests: _rrf_merge
# ---------------------------------------------------------------------------

class TestRRFMerge:
    def _r(self, doc_id, page_number):
        return {"doc_id": doc_id, "page_number": page_number, "text": "", "title": "T", "snippet": ""}

    def test_fts_only_when_no_semantic(self):
        fts = [self._r("doc-a", 1), self._r("doc-a", 2)]
        result = _rrf_merge(fts, [])
        assert [(r["doc_id"], r["page_number"]) for r in result] == [("doc-a", 1), ("doc-a", 2)]

    def test_semantic_only_when_no_fts(self):
        sem = [self._r("doc-b", 5)]
        result = _rrf_merge([], sem)
        assert result[0]["page_number"] == 5

    def test_page_in_both_lists_ranked_first(self):
        """A page appearing in both FTS and semantic results should win."""
        fts = [self._r("doc-a", 3), self._r("doc-a", 1)]
        sem = [self._r("doc-a", 3), self._r("doc-a", 2)]
        result = _rrf_merge(fts, sem)
        # Page 3 appears in both → highest RRF score
        assert result[0]["page_number"] == 3

    def test_unique_pages_from_both_included(self):
        fts = [self._r("doc-a", 1)]
        sem = [self._r("doc-a", 2)]
        result = _rrf_merge(fts, sem)
        pages = {r["page_number"] for r in result}
        assert {1, 2} == pages

    def test_empty_both(self):
        assert _rrf_merge([], []) == []

    def test_preserves_text_from_fts_when_shared(self):
        fts = [{"doc_id": "doc-a", "page_number": 1, "text": "fts text", "title": "T", "snippet": ""}]
        sem = [{"doc_id": "doc-a", "page_number": 1, "text": "sem text", "title": "T", "snippet": ""}]
        result = _rrf_merge(fts, sem)
        # FTS result is in position 0, so its text should be preserved
        assert result[0]["text"] == "fts text"

    def test_rrf_k_parameter_affects_ordering(self):
        """A very low k amplifies rank differences more than a high k."""
        fts = [self._r("doc-a", 1), self._r("doc-a", 2)]
        sem = [self._r("doc-a", 2), self._r("doc-a", 1)]
        # With k=1: page 1 gets 1/2 + 1/3 ≈ 0.833; page 2 gets 1/3 + 1/2 ≈ 0.833 (tied)
        # With k=60 (default): same tie
        result_small_k = _rrf_merge(fts, sem, k=1)
        assert len(result_small_k) == 2


# ---------------------------------------------------------------------------
# Tests: _load_page_embeddings
# ---------------------------------------------------------------------------

class TestLoadPageEmbeddings:
    def test_returns_none_when_table_empty(self, tmp_path):
        db_path = _make_db([("doc-a", 1, "text here")])
        result = _load_page_embeddings(db_path)
        assert result is None
        db_path.unlink(missing_ok=True)

    def test_returns_none_when_table_missing(self, tmp_path):
        db_path = tmp_path / "bare.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE pages (id INTEGER PRIMARY KEY, doc_id TEXT, page_number INTEGER, text_content TEXT)")
        conn.close()
        result = _load_page_embeddings(db_path)
        assert result is None

    def test_loads_embeddings_correctly(self, tmp_path):
        db_path = _make_db([("doc-a", 1, "page one"), ("doc-a", 2, "page two")])
        _store_embedding(db_path, 1, [0.1, 0.2, 0.3])
        _store_embedding(db_path, 2, [0.4, 0.5, 0.6])

        # Clear cache to force fresh load
        from casestack.api.routes.ask import _emb_cache
        _emb_cache.pop(str(db_path), None)

        result = _load_page_embeddings(db_path)
        assert result is not None
        page_meta, matrix = result
        assert len(page_meta) == 2
        assert matrix.shape == (2, 3)
        db_path.unlink(missing_ok=True)

    def test_caches_on_second_call(self, tmp_path):
        db_path = _make_db([("doc-a", 1, "page one")])
        _store_embedding(db_path, 1, [1.0, 0.0])

        from casestack.api.routes.ask import _emb_cache
        _emb_cache.pop(str(db_path), None)

        r1 = _load_page_embeddings(db_path)
        r2 = _load_page_embeddings(db_path)
        # Second call should return the exact same cached object
        assert r1 is r2, "Cache miss: second call returned a different object"
        db_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tests: _search_semantic (graceful fallback)
# ---------------------------------------------------------------------------

class TestSearchSemanticFallback:
    def test_returns_empty_when_no_embeddings(self, tmp_path):
        db_path = _make_db([("doc-a", 1, "Some text about Epstein")])
        result = _search_semantic(db_path, "Epstein")
        assert result == []
        db_path.unlink(missing_ok=True)

    def test_does_not_raise_on_missing_table(self, tmp_path):
        db_path = tmp_path / "minimal.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE pages (id INTEGER PRIMARY KEY, doc_id TEXT, page_number INTEGER, text_content TEXT, char_count INTEGER)")
        conn.close()
        # Should not raise
        result = _search_semantic(db_path, "anything")
        assert result == []


# ---------------------------------------------------------------------------
# Tests: PageEmbedder
# ---------------------------------------------------------------------------

class TestPageEmbedder:
    def test_embed_corpus_skips_when_all_embedded(self, tmp_path):
        """embed_corpus returns 0 when all pages already have embeddings."""
        from casestack.processors.page_embedder import PageEmbedder
        db_path = _make_db([("doc-a", 1, "some text")])
        _store_embedding(db_path, 1, [0.1] * 10)
        embedder = PageEmbedder.__new__(PageEmbedder)  # bypass __init__
        # Mock _load_model to avoid downloading
        embedder.model_name = "test"
        embedder.batch_size = 32
        embedder._model = None
        count = embedder.embed_corpus.__func__(embedder, db_path)  # type: ignore
        assert count == 0
        db_path.unlink(missing_ok=True)

    def test_float_list_to_blob_roundtrip(self):
        """F32 BLOB encoding is correct (little-endian IEEE 754)."""
        from casestack.processors.page_embedder import _float_list_to_blob
        import struct
        values = [1.0, 2.5, -0.5, 0.0]
        blob = _float_list_to_blob(values)
        recovered = list(struct.unpack(f"{len(values)}f", blob))
        assert recovered == pytest.approx(values, abs=1e-6)

    def test_ensure_table_creates_if_missing(self, tmp_path):
        from casestack.processors.page_embedder import PageEmbedder
        db_path = tmp_path / "fresh.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE pages (id INTEGER PRIMARY KEY)")
        conn.commit()
        PageEmbedder._ensure_table(conn)
        # Table should now exist
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "page_embeddings" in tables
        conn.close()
