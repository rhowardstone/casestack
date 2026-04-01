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
                project_slug TEXT,
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

            -- Projects: named investigation boards that aggregate datasets
            CREATE TABLE IF NOT EXISTS projects (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                last_opened_at TEXT
            );

            -- Many-to-many: a project has many datasets (cases), a dataset can be in many projects
            CREATE TABLE IF NOT EXISTS project_datasets (
                project_slug TEXT NOT NULL REFERENCES projects(slug) ON DELETE CASCADE,
                dataset_slug TEXT NOT NULL REFERENCES cases(slug) ON DELETE CASCADE,
                added_at TEXT NOT NULL,
                PRIMARY KEY (project_slug, dataset_slug)
            );
        """)
        # Auto-migrate: every existing case that has no project gets a 1-to-1 project
        self._auto_migrate_cases_to_projects(conn)
        conn.commit()
        conn.close()

    def _auto_migrate_cases_to_projects(self, conn: "sqlite3.Connection") -> None:
        """Create a project for every case that doesn't already have one."""
        cases = conn.execute("SELECT slug, name, description, created_at FROM cases").fetchall()
        for case in cases:
            slug = case["slug"]
            exists = conn.execute(
                "SELECT 1 FROM projects WHERE slug = ?", (slug,)
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO projects (slug, name, description, created_at) VALUES (?, ?, ?, ?)",
                    (slug, case["name"], case["description"] or "", case["created_at"]),
                )
            linked = conn.execute(
                "SELECT 1 FROM project_datasets WHERE project_slug = ? AND dataset_slug = ?",
                (slug, slug),
            ).fetchone()
            if not linked:
                conn.execute(
                    "INSERT INTO project_datasets (project_slug, dataset_slug, added_at) VALUES (?, ?, ?)",
                    (slug, slug, case["created_at"]),
                )

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

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def create_conversation(self, case_slug: str, title: str | None = None) -> dict:
        import uuid
        conn = self._connect()
        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO conversations (id, case_slug, created_at, updated_at, title) VALUES (?, ?, ?, ?, ?)",
            (conv_id, case_slug, now, now, title),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        conn.close()
        return dict(row)

    def list_conversations(self, case_slug: str) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM conversations WHERE case_slug = ? ORDER BY updated_at DESC",
            (case_slug,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_conversation(self, conv_id: str) -> dict | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_conversation_messages(self, conv_id: str) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM conversation_messages WHERE conversation_id = ? ORDER BY id ASC",
            (conv_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        sources: list | None = None,
        queries: list | None = None,
    ) -> dict:
        import json as _json
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            """INSERT INTO conversation_messages
               (conversation_id, role, content, sources_json, queries_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                conv_id,
                role,
                content,
                _json.dumps(sources) if sources is not None else None,
                _json.dumps(queries) if queries is not None else None,
                now,
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conv_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM conversation_messages WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        conn.close()
        return dict(row)

    def update_conversation_title(self, conv_id: str, title: str) -> None:
        conn = self._connect()
        conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conv_id))
        conn.commit()
        conn.close()

    def delete_conversation(self, conv_id: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def create_project(self, *, slug: str, name: str, description: str = "") -> dict:
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO projects (slug, name, description, created_at) VALUES (?, ?, ?, ?)",
            (slug, name, description, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
        conn.close()
        return dict(row)

    def list_projects(self) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY last_opened_at DESC, created_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_project(self, slug: str) -> dict | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def delete_project(self, slug: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM projects WHERE slug = ?", (slug,))
        conn.commit()
        conn.close()

    def get_project_datasets(self, project_slug: str) -> list[dict]:
        """Return all cases (datasets) linked to a project."""
        conn = self._connect()
        rows = conn.execute(
            """SELECT c.*, pd.added_at AS linked_at
               FROM cases c
               JOIN project_datasets pd ON pd.dataset_slug = c.slug
               WHERE pd.project_slug = ?
               ORDER BY pd.added_at ASC""",
            (project_slug,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_dataset_to_project(self, project_slug: str, dataset_slug: str) -> None:
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO project_datasets (project_slug, dataset_slug, added_at) VALUES (?, ?, ?)",
            (project_slug, dataset_slug, now),
        )
        conn.commit()
        conn.close()

    def remove_dataset_from_project(self, project_slug: str, dataset_slug: str) -> None:
        conn = self._connect()
        conn.execute(
            "DELETE FROM project_datasets WHERE project_slug = ? AND dataset_slug = ?",
            (project_slug, dataset_slug),
        )
        conn.commit()
        conn.close()

    def touch_project(self, slug: str) -> None:
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE projects SET last_opened_at = ? WHERE slug = ?", (now, slug))
        conn.commit()
        conn.close()
