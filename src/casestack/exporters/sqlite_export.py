"""SQLite exporter for CaseStack.

Creates a self-contained SQLite database with documents, pages (per-page text),
persons, and a many-to-many join table.  Includes FTS5 full-text search on the
pages table for page-level search, plus additional tables for redaction scores,
recovered text, transcripts, extracted entities, and extracted images.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from rich.console import Console

logger = logging.getLogger(__name__)

from casestack.models.document import Document, Page, Person
from casestack.models.forensics import (
    ExtractedEntity,
    ExtractedImage,
    PageCaption,
    RecoveredText,
    RedactionScore,
    Transcript,
)

# ---------------------------------------------------------------------------
# DDL statements
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
-- Core tables
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

CREATE TABLE IF NOT EXISTS persons (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    aliases TEXT,
    category TEXT NOT NULL,
    short_bio TEXT
);

CREATE TABLE IF NOT EXISTS document_persons (
    document_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    PRIMARY KEY (document_id, person_id)
);

-- Forensic analysis tables
CREATE TABLE IF NOT EXISTS redaction_scores (
    document_id TEXT PRIMARY KEY,
    total_redactions INTEGER DEFAULT 0,
    proper_redactions INTEGER DEFAULT 0,
    improper_redactions INTEGER DEFAULT 0,
    redaction_density REAL DEFAULT 0,
    page_count INTEGER
);

CREATE TABLE IF NOT EXISTS recovered_text (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    confidence REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transcripts (
    document_id TEXT PRIMARY KEY,
    source_path TEXT,
    text TEXT NOT NULL,
    language TEXT DEFAULT 'en',
    duration_seconds REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS extracted_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    text TEXT NOT NULL,
    confidence REAL DEFAULT 0,
    person_id TEXT
);

CREATE TABLE IF NOT EXISTS extracted_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    page_number INTEGER,
    image_index INTEGER,
    width INTEGER,
    height INTEGER,
    format TEXT,
    file_path TEXT,
    description TEXT,
    size_bytes INTEGER DEFAULT 0
);

-- Vector embedding chunks (BLOB for portable SQLite; F32_BLOB for Turso)
CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding BLOB,
    UNIQUE(document_id, chunk_index)
);

-- FTS5 on pages (THE critical feature)
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    text_content,
    content='pages',
    content_rowid='id'
);

-- FTS5 sync triggers
CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, text_content) VALUES (new.id, new.text_content);
END;

CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, text_content) VALUES ('delete', old.id, old.text_content);
END;

CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, text_content) VALUES ('delete', old.id, old.text_content);
    INSERT INTO pages_fts(rowid, text_content) VALUES (new.id, new.text_content);
END;

-- FTS5 on transcripts
CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    text,
    content='transcripts',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
    INSERT INTO transcripts_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;

CREATE TRIGGER IF NOT EXISTS transcripts_au AFTER UPDATE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    INSERT INTO transcripts_fts(rowid, text) VALUES (new.rowid, new.text);
END;

-- Indices
CREATE INDEX IF NOT EXISTS idx_pages_doc_page ON pages(doc_id, page_number);
CREATE INDEX IF NOT EXISTS idx_pages_docid ON pages(document_id);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
CREATE INDEX IF NOT EXISTS idx_persons_slug ON persons(slug);
CREATE INDEX IF NOT EXISTS idx_persons_category ON persons(category);
CREATE INDEX IF NOT EXISTS idx_dp_document ON document_persons(document_id);
CREATE INDEX IF NOT EXISTS idx_dp_person ON document_persons(person_id);
CREATE INDEX IF NOT EXISTS idx_recovered_doc ON recovered_text(document_id);
CREATE INDEX IF NOT EXISTS idx_entities_doc ON extracted_entities(document_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON extracted_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_images_doc ON extracted_images(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);

-- Image captions for image-heavy pages
CREATE TABLE IF NOT EXISTS page_captions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    caption TEXT NOT NULL,
    ocr_text TEXT,
    UNIQUE(document_id, page_number)
);

CREATE INDEX IF NOT EXISTS idx_captions_doc ON page_captions(document_id);

-- FTS5 on captions for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS captions_fts USING fts5(
    caption, ocr_text,
    content='page_captions',
    content_rowid='id'
);

-- FTS sync triggers for captions
CREATE TRIGGER IF NOT EXISTS captions_ai AFTER INSERT ON page_captions BEGIN
    INSERT INTO captions_fts(rowid, caption, ocr_text)
    VALUES (new.id, new.caption, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS captions_ad AFTER DELETE ON page_captions BEGIN
    INSERT INTO captions_fts(captions_fts, rowid, caption, ocr_text)
    VALUES ('delete', old.id, old.caption, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS captions_au AFTER UPDATE ON page_captions BEGIN
    INSERT INTO captions_fts(captions_fts, rowid, caption, ocr_text)
    VALUES ('delete', old.id, old.caption, old.ocr_text);
    INSERT INTO captions_fts(rowid, caption, ocr_text)
    VALUES (new.id, new.caption, new.ocr_text);
END;
"""

DEFAULT_DB_NAME = "corpus.db"


class SqliteExporter:
    """Export documents, pages, persons, and forensic data to a SQLite database."""

    def __init__(self) -> None:
        self._console = Console()

    def export(
        self,
        documents: list[Document],
        persons: list[Person],
        db_path: Path,
        *,
        pages: list[Page] | None = None,
        redaction_scores: list[RedactionScore] | None = None,
        recovered_texts: list[RecoveredText] | None = None,
        transcripts: list[Transcript] | None = None,
        entities: list[ExtractedEntity] | None = None,
        images: list[ExtractedImage] | None = None,
        captions: list[PageCaption] | None = None,
    ) -> Path:
        """Create a SQLite database with all pipeline data.

        Parameters
        ----------
        documents:
            List of Document models.
        persons:
            List of Person models.
        db_path:
            Output database file path.
        pages:
            Optional list of Page models for per-page text storage.
        redaction_scores:
            Optional redaction analysis scores.
        recovered_texts:
            Optional text recovered from redactions.
        transcripts:
            Optional audio/video transcripts.
        entities:
            Optional extracted entities.
        images:
            Optional extracted image metadata.

        Returns
        -------
        Path
            The path to the created database file.
        """
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        if db_path.exists():
            db_path.unlink()

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(_SCHEMA_SQL)

            self._insert_persons(conn, persons)
            doc_id_map = self._insert_documents(conn, documents, pages or [])
            self._insert_pages(conn, pages or [], doc_id_map)
            self._insert_document_persons(conn, documents)

            if redaction_scores:
                self._insert_redaction_scores(conn, redaction_scores)
            if recovered_texts:
                self._insert_recovered_text(conn, recovered_texts)
            if transcripts:
                self._insert_transcripts(conn, transcripts)
            if entities:
                self._insert_entities(conn, entities)
            if images:
                self._insert_images(conn, images)
            if captions:
                self._insert_captions(conn, captions)

            # Optimize FTS5 indices
            conn.execute("INSERT INTO pages_fts(pages_fts) VALUES ('optimize')")
            conn.execute("INSERT INTO transcripts_fts(transcripts_fts) VALUES ('optimize')")
            if captions:
                conn.execute("INSERT INTO captions_fts(captions_fts) VALUES ('optimize')")
            conn.execute("ANALYZE")
            conn.commit()

        finally:
            conn.close()

        page_count = len(pages) if pages else 0
        size_mb = db_path.stat().st_size / (1024 * 1024)
        self._console.print(f"\n[green]Created SQLite database at {db_path.resolve()}[/green]")
        self._console.print(f"  Documents:        {len(documents):,}")
        self._console.print(f"  Pages:            {page_count:,}")
        self._console.print(f"  Persons:          {len(persons):,}")
        if redaction_scores:
            self._console.print(f"  Redaction scores: {len(redaction_scores):,}")
        if recovered_texts:
            self._console.print(f"  Recovered texts:  {len(recovered_texts):,}")
        if transcripts:
            self._console.print(f"  Transcripts:      {len(transcripts):,}")
        if entities:
            self._console.print(f"  Entities:         {len(entities):,}")
        if images:
            self._console.print(f"  Images:           {len(images):,}")
        if captions:
            self._console.print(f"  Captions:         {len(captions):,}")
        self._console.print(f"  Size:             {size_mb:.1f} MB")
        self._console.print("  FTS5 index:       pages.text_content, transcripts.text")

        return db_path

    # ------------------------------------------------------------------
    # Core table inserts
    # ------------------------------------------------------------------

    def _insert_persons(self, conn: sqlite3.Connection, persons: list[Person]) -> None:
        rows = [
            (
                p.id,
                p.slug,
                p.name,
                "; ".join(p.aliases) if p.aliases else None,
                p.category,
                p.shortBio,
            )
            for p in persons
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO persons"
            " (id, slug, name, aliases, category, short_bio)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._console.print(f"  [dim]Inserted {len(rows):,} persons[/dim]")

    def _insert_documents(
        self,
        conn: sqlite3.Connection,
        documents: list[Document],
        pages: list[Page],
    ) -> dict[str, int]:
        """Insert documents and return a mapping of doc_id -> autoincrement id."""
        # Pre-compute page stats per document
        page_counts: dict[str, int] = {}
        char_counts: dict[str, int] = {}
        for p in pages:
            page_counts[p.document_id] = page_counts.get(p.document_id, 0) + 1
            char_counts[p.document_id] = char_counts.get(p.document_id, 0) + p.char_count

        doc_id_map: dict[str, int] = {}
        for doc in documents:
            total_pages = page_counts.get(doc.id, doc.pageCount or 0)
            total_chars = char_counts.get(doc.id, len(doc.ocrText) if doc.ocrText else 0)
            conn.execute(
                """INSERT OR REPLACE INTO documents
                   (doc_id, title, date, source, category, summary,
                    total_pages, total_chars, file_path, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc.id,
                    doc.title,
                    doc.date,
                    doc.source,
                    doc.category,
                    doc.summary,
                    total_pages,
                    total_chars,
                    doc.pdfUrl,
                    "; ".join(doc.tags) if doc.tags else None,
                ),
            )
            # Get the autoincrement id
            row = conn.execute(
                "SELECT id FROM documents WHERE doc_id = ?", (doc.id,)
            ).fetchone()
            if row:
                doc_id_map[doc.id] = row[0]

        self._console.print(f"  [dim]Inserted {len(documents):,} documents[/dim]")
        return doc_id_map

    def _insert_pages(
        self,
        conn: sqlite3.Connection,
        pages: list[Page],
        doc_id_map: dict[str, int],
    ) -> None:
        """Insert pages with both document_id (int FK) and doc_id (text for joins)."""
        rows = []
        skipped = 0
        for p in pages:
            fk = doc_id_map.get(p.document_id)
            if fk is None:
                logger.warning(
                    "Page for unknown document_id=%s, page=%d — skipping",
                    p.document_id,
                    p.page_number,
                )
                skipped += 1
                continue
            rows.append((fk, p.document_id, p.page_number, p.text_content, p.char_count))
        conn.executemany(
            """INSERT INTO pages
               (document_id, doc_id, page_number, text_content, char_count)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
        if skipped:
            self._console.print(f"  [yellow]Skipped {skipped} orphan pages[/yellow]")
        self._console.print(f"  [dim]Inserted {len(rows):,} pages[/dim]")

    def _insert_document_persons(
        self, conn: sqlite3.Connection, documents: list[Document]
    ) -> None:
        rows = [(doc.id, pid) for doc in documents for pid in doc.personIds]
        if rows:
            conn.executemany(
                "INSERT OR IGNORE INTO document_persons (document_id, person_id)"
                " VALUES (?, ?)",
                rows,
            )
        self._console.print(f"  [dim]Inserted {len(rows):,} document-person links[/dim]")

    # ------------------------------------------------------------------
    # Forensic table inserts
    # ------------------------------------------------------------------

    def _insert_redaction_scores(
        self, conn: sqlite3.Connection, scores: list[RedactionScore]
    ) -> None:
        rows = [
            (
                s.document_id,
                s.total_redactions,
                s.proper_redactions,
                s.improper_redactions,
                s.redaction_density,
                s.page_count,
            )
            for s in scores
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO redaction_scores
               (document_id, total_redactions, proper_redactions, improper_redactions,
                redaction_density, page_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._console.print(f"  [dim]Inserted {len(rows):,} redaction scores[/dim]")

    def _insert_recovered_text(
        self, conn: sqlite3.Connection, texts: list[RecoveredText]
    ) -> None:
        rows = [(t.document_id, t.page_number, t.text, t.confidence) for t in texts]
        conn.executemany(
            "INSERT INTO recovered_text"
            " (document_id, page_number, text, confidence)"
            " VALUES (?, ?, ?, ?)",
            rows,
        )
        self._console.print(f"  [dim]Inserted {len(rows):,} recovered text entries[/dim]")

    def _insert_transcripts(
        self, conn: sqlite3.Connection, transcripts: list[Transcript]
    ) -> None:
        rows = [
            (t.document_id, t.source_path, t.text, t.language, t.duration_seconds)
            for t in transcripts
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO transcripts
               (document_id, source_path, text, language, duration_seconds)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
        self._console.print(f"  [dim]Inserted {len(rows):,} transcripts[/dim]")

    def _insert_entities(
        self, conn: sqlite3.Connection, entities: list[ExtractedEntity]
    ) -> None:
        rows = [
            (e.document_id, e.entity_type, e.text, e.confidence, e.person_id)
            for e in entities
        ]
        conn.executemany(
            "INSERT INTO extracted_entities"
            " (document_id, entity_type, text, confidence, person_id)"
            " VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self._console.print(f"  [dim]Inserted {len(rows):,} entities[/dim]")

    def _insert_images(
        self, conn: sqlite3.Connection, images: list[ExtractedImage]
    ) -> None:
        rows = [
            (
                i.document_id,
                i.page_number,
                i.image_index,
                i.width,
                i.height,
                i.format,
                i.file_path,
                i.description,
                i.size_bytes,
            )
            for i in images
        ]
        conn.executemany(
            """INSERT INTO extracted_images
               (document_id, page_number, image_index, width, height, format,
                file_path, description, size_bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._console.print(f"  [dim]Inserted {len(rows):,} images[/dim]")

    def _insert_captions(
        self, conn: sqlite3.Connection, captions: list[PageCaption]
    ) -> None:
        rows = [
            (c.document_id, c.page_number, c.caption, c.ocr_text)
            for c in captions
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO page_captions
               (document_id, page_number, caption, ocr_text)
               VALUES (?, ?, ?, ?)""",
            rows,
        )
        self._console.print(f"  [dim]Inserted {len(rows):,} page captions[/dim]")
