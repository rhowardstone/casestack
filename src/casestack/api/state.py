"""App state database — tracks registered cases, ingest runs, conversations."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class AppState:
    """Manages the CaseStack app state SQLite database."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_db(self) -> None:
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                case_yaml_path TEXT NOT NULL,
                output_dir TEXT NOT NULL,
                documents_dir TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_opened_at TEXT,
                document_count INTEGER DEFAULT 0,
                page_count INTEGER DEFAULT 0,
                image_count INTEGER DEFAULT 0,
                transcript_count INTEGER DEFAULT 0,
                entity_count INTEGER DEFAULT 0,
                db_size_bytes INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS ingest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_slug TEXT NOT NULL REFERENCES cases(slug) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT DEFAULT 'running',
                current_step TEXT,
                progress_json TEXT,
                error_message TEXT,
                stats_json TEXT
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                case_slug TEXT NOT NULL REFERENCES cases(slug) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                title TEXT
            );

            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources_json TEXT,
                queries_json TEXT,
                created_at TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()

    def register_case(self, *, slug: str, name: str, description: str,
                      case_yaml_path: str, output_dir: str,
                      documents_dir: str) -> dict:
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO cases
               (slug, name, description, case_yaml_path, output_dir,
                documents_dir, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (slug, name, description, case_yaml_path, output_dir,
             documents_dir, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM cases WHERE slug = ?", (slug,)).fetchone()
        conn.close()
        return dict(row)

    def list_cases(self) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM cases ORDER BY last_opened_at DESC, created_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_case(self, slug: str) -> dict | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM cases WHERE slug = ?", (slug,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_case(self, slug: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM cases WHERE slug = ?", (slug,))
        conn.commit()
        conn.close()

    def update_case_stats(self, slug: str, **kwargs) -> None:
        allowed = {"document_count", "page_count", "image_count",
                   "transcript_count", "entity_count", "db_size_bytes",
                   "last_opened_at"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        conn = self._connect()
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE cases SET {sets} WHERE slug = ?",
                     (*fields.values(), slug))
        conn.commit()
        conn.close()
