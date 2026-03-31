"""Page-level embedding generator for hybrid FTS5 + semantic search.

Reads all pages from a corpus SQLite DB, embeds each page's text_content
using sentence-transformers, and writes the resulting F32 BLOBs to the
`page_embeddings` table in the same DB.

Unlike the document_chunks embedder (which chunks across page boundaries),
this embedder operates at page granularity — matching the retrieval unit
used by the FTS5 pipeline so results from both systems can be merged directly.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import struct
from pathlib import Path

logger = logging.getLogger(__name__)

# Default model: all-MiniLM-L6-v2 is ~45 MB, loads in <2 s, good multilingual
# recall for legal/government text. Override with CASESTACK_EMBEDDING_MODEL env var.
_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_DIMS = 384


def _float_list_to_blob(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


class PageEmbedder:
    """Generate and store page-level embeddings for a corpus DB.

    Parameters
    ----------
    model_name : str
        sentence-transformers model identifier.
    batch_size : int
        Pages per encoding batch.
    """

    def __init__(
        self,
        model_name: str | None = None,
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name or os.environ.get(
            "CASESTACK_EMBEDDING_MODEL", _DEFAULT_MODEL
        )
        self.batch_size = batch_size
        self._model = None  # lazy load

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for semantic search. "
                "Install with: pip install 'casestack[embeddings]'"
            ) from exc
        logger.info("Loading embedding model: %s", self.model_name)
        self._model = SentenceTransformer(self.model_name, trust_remote_code=True)
        return self._model

    def embed_corpus(self, db_path: Path, *, overwrite: bool = False) -> int:
        """Embed all pages in *db_path* and store in `page_embeddings`.

        Returns the number of pages embedded.  Skips pages that already
        have embeddings unless *overwrite* is True.
        """
        conn = sqlite3.connect(str(db_path))
        self._ensure_table(conn)

        if overwrite:
            conn.execute("DELETE FROM page_embeddings")
            conn.commit()

        # Fetch pages that don't have embeddings yet
        rows = conn.execute(
            "SELECT p.id, p.text_content "
            "FROM pages p "
            "LEFT JOIN page_embeddings pe ON pe.page_id = p.id "
            "WHERE pe.page_id IS NULL AND length(p.text_content) > 20 "
            "ORDER BY p.id"
        ).fetchall()

        if not rows:
            logger.info("All pages already embedded (or no pages found).")
            conn.close()
            return 0

        model = self._load_model()
        dims = model.get_sentence_embedding_dimension() or _DEFAULT_DIMS

        logger.info(
            "Embedding %d pages with %s (dims=%d, batch=%d)",
            len(rows),
            self.model_name,
            dims,
            self.batch_size,
        )

        total = 0
        for i in range(0, len(rows), self.batch_size):
            batch = rows[i : i + self.batch_size]
            page_ids = [r[0] for r in batch]
            texts = [r[1] for r in batch]

            embeddings = model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

            for page_id, emb in zip(page_ids, embeddings):
                blob = _float_list_to_blob(emb.tolist())
                conn.execute(
                    "INSERT OR REPLACE INTO page_embeddings"
                    " (page_id, model, dims, embedding) VALUES (?, ?, ?, ?)",
                    (page_id, self.model_name, dims, blob),
                )

            conn.commit()
            total += len(batch)
            logger.info("  Embedded %d / %d pages", total, len(rows))

        conn.close()
        logger.info("Done. Embedded %d pages into %s", total, db_path.name)
        return total

    @staticmethod
    def _ensure_table(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_embeddings (
                page_id   INTEGER PRIMARY KEY REFERENCES pages(id),
                model     TEXT NOT NULL,
                dims      INTEGER NOT NULL,
                embedding BLOB NOT NULL
            )
        """)
        conn.commit()
