"""Tests for app state database."""
from pathlib import Path

from casestack.api.state import AppState


def test_init_creates_tables(tmp_path):
    db_path = tmp_path / "state.db"
    state = AppState(db_path)
    state.init_db()
    # Verify tables exist
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "cases" in tables
    assert "ingest_runs" in tables
    assert "conversations" in tables
    assert "conversation_messages" in tables


def test_register_and_list_cases(tmp_path):
    state = AppState(tmp_path / "state.db")
    state.init_db()
    state.register_case(
        slug="test-case",
        name="Test Case",
        description="A test",
        case_yaml_path="/tmp/case.yaml",
        output_dir="/tmp/output/test-case",
        documents_dir="/tmp/docs",
    )
    cases = state.list_cases()
    assert len(cases) == 1
    assert cases[0]["slug"] == "test-case"
    assert cases[0]["name"] == "Test Case"


def test_get_case(tmp_path):
    state = AppState(tmp_path / "state.db")
    state.init_db()
    state.register_case(
        slug="my-case", name="My Case", description="",
        case_yaml_path="/tmp/c.yaml", output_dir="/tmp/o",
        documents_dir="/tmp/d",
    )
    case = state.get_case("my-case")
    assert case is not None
    assert case["name"] == "My Case"
    assert state.get_case("nonexistent") is None


def test_delete_case(tmp_path):
    state = AppState(tmp_path / "state.db")
    state.init_db()
    state.register_case(
        slug="del-me", name="Delete Me", description="",
        case_yaml_path="/x", output_dir="/x", documents_dir="/x",
    )
    assert state.get_case("del-me") is not None
    state.delete_case("del-me")
    assert state.get_case("del-me") is None


def test_update_case_stats(tmp_path):
    state = AppState(tmp_path / "state.db")
    state.init_db()
    state.register_case(
        slug="s", name="S", description="",
        case_yaml_path="/x", output_dir="/x", documents_dir="/x",
    )
    state.update_case_stats("s", document_count=100, page_count=5000)
    case = state.get_case("s")
    assert case["document_count"] == 100
    assert case["page_count"] == 5000
