"""Tests for the serve layer: custom templates, datasette config, and CLI args.

Covers:
- Templates directory exists and contains index.html
- Generated datasette.yaml includes pages table config and allow_sql
- Serve command constructs the correct subprocess arguments
- Immutable mode flag works correctly
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from casestack.case import CaseConfig


# ---------------------------------------------------------------------------
# Templates directory tests
# ---------------------------------------------------------------------------


class TestTemplatesDirectory:
    def test_templates_dir_exists(self):
        """The templates directory must exist as a package resource."""
        import importlib.resources

        templates_dir = importlib.resources.files("casestack") / "templates"
        assert templates_dir.is_dir(), f"Templates directory not found: {templates_dir}"

    def test_index_html_exists(self):
        """index.html must exist in the templates directory."""
        import importlib.resources

        templates_dir = importlib.resources.files("casestack") / "templates"
        index_html = templates_dir / "index.html"
        assert index_html.is_file(), f"index.html not found: {index_html}"

    def test_index_html_contains_search_elements(self):
        """index.html must contain key search UI elements."""
        import importlib.resources

        templates_dir = importlib.resources.files("casestack") / "templates"
        index_html = templates_dir / "index.html"
        content = index_html.read_text(encoding="utf-8")

        # Check for essential HTML elements
        assert 'id="search"' in content, "Missing search input element"
        assert 'id="results"' in content, "Missing results container"
        assert "pages_fts" in content, "Missing FTS5 table reference"
        assert "doSearch" in content, "Missing doSearch function"
        assert "snippet(" in content, "Missing FTS5 snippet function call"

    def test_index_html_has_datasette_template_variables(self):
        """index.html should use Datasette template variables."""
        import importlib.resources

        templates_dir = importlib.resources.files("casestack") / "templates"
        index_html = templates_dir / "index.html"
        content = index_html.read_text(encoding="utf-8")

        assert "{{ metadata.title" in content, "Missing metadata.title template variable"
        assert "{{ metadata.description" in content, "Missing metadata.description template variable"
        assert "{{ database" in content, "Missing database template variable"


# ---------------------------------------------------------------------------
# Datasette config generation tests
# ---------------------------------------------------------------------------


class TestDatasetteConfig:
    def _make_case(self, tmpdir: Path) -> CaseConfig:
        """Create a minimal CaseConfig pointing to tmpdir."""
        docs_dir = tmpdir / "docs"
        docs_dir.mkdir()
        return CaseConfig(
            name="Test Case",
            slug="test-case",
            description="A test case for unit tests",
            documents_dir=docs_dir,
        )

    def test_config_has_pages_table(self):
        """Generated datasette.yaml must include pages table config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            case = self._make_case(tmpdir)
            output_dir = tmpdir / "output" / "test-case"
            output_dir.mkdir(parents=True)

            # Temporarily override output_dir property
            db_path = output_dir / "test-case.db"
            db_path.touch()

            from casestack.ingest import _generate_datasette_config

            # Monkey-patch output_dir for testing
            original_output_dir = CaseConfig.output_dir.fget
            CaseConfig.output_dir = property(lambda self: output_dir)
            try:
                _generate_datasette_config(case, db_path)
            finally:
                CaseConfig.output_dir = property(original_output_dir)

            config_path = output_dir / "datasette.yaml"
            assert config_path.exists(), "datasette.yaml was not created"

            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            tables = config["databases"]["test-case"]["tables"]

            assert "documents" in tables
            assert tables["documents"]["label_column"] == "title"
            assert "pages" in tables
            assert tables["pages"]["description"] == "Per-page text content"
            assert "pages_fts" in tables
            assert tables["pages_fts"]["hidden"] is True

    def test_config_has_allow_sql(self):
        """Generated datasette.yaml must include allow_sql: true for custom SQL queries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            case = self._make_case(tmpdir)
            output_dir = tmpdir / "output" / "test-case"
            output_dir.mkdir(parents=True)

            db_path = output_dir / "test-case.db"
            db_path.touch()

            from casestack.ingest import _generate_datasette_config

            original_output_dir = CaseConfig.output_dir.fget
            CaseConfig.output_dir = property(lambda self: output_dir)
            try:
                _generate_datasette_config(case, db_path)
            finally:
                CaseConfig.output_dir = property(original_output_dir)

            config_path = output_dir / "datasette.yaml"
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

            assert config["settings"]["allow_sql"] is True

    def test_config_title_uses_case_name(self):
        """Generated config should derive title from case name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            case = self._make_case(tmpdir)
            output_dir = tmpdir / "output" / "test-case"
            output_dir.mkdir(parents=True)

            db_path = output_dir / "test-case.db"
            db_path.touch()

            from casestack.ingest import _generate_datasette_config

            original_output_dir = CaseConfig.output_dir.fget
            CaseConfig.output_dir = property(lambda self: output_dir)
            try:
                _generate_datasette_config(case, db_path)
            finally:
                CaseConfig.output_dir = property(original_output_dir)

            config_path = output_dir / "datasette.yaml"
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

            assert "Test Case" in config["title"]


# ---------------------------------------------------------------------------
# Serve command argument construction tests
# ---------------------------------------------------------------------------


class TestServeCommand:
    def _make_case_with_db(self, tmpdir: Path) -> tuple[CaseConfig, Path]:
        """Create a CaseConfig with a fake database file."""
        docs_dir = tmpdir / "docs"
        docs_dir.mkdir()
        case = CaseConfig(
            name="Test Case",
            slug="test-case",
            documents_dir=docs_dir,
            serve_port=8001,
        )
        output_dir = tmpdir / "output" / "test-case"
        output_dir.mkdir(parents=True)
        db_path = output_dir / "test-case.db"
        db_path.touch()
        ds_config = output_dir / "datasette.yaml"
        ds_config.write_text("title: Test", encoding="utf-8")
        return case, db_path

    @patch("casestack.cli.subprocess.run")
    @patch("casestack.cli._load_case")
    def test_serve_basic_args(self, mock_load_case, mock_subprocess_run):
        """Serve command should include datasette serve, host, port, and template-dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            case, db_path = self._make_case_with_db(tmpdir)

            # Override the properties to use our temp paths
            original_output_dir = CaseConfig.output_dir.fget
            original_db_path = CaseConfig.db_path.fget
            CaseConfig.output_dir = property(lambda self: tmpdir / "output" / "test-case")
            CaseConfig.db_path = property(lambda self: tmpdir / "output" / "test-case" / "test-case.db")

            mock_load_case.return_value = case

            try:
                from click.testing import CliRunner

                from casestack.cli import cli

                runner = CliRunner()
                result = runner.invoke(cli, ["serve", "--host", "127.0.0.1", "--port", "9999"])

                # Check the command was called
                assert mock_subprocess_run.called, "subprocess.run was not called"
                cmd = mock_subprocess_run.call_args[0][0]

                # Verify key arguments
                assert "-m" in cmd
                assert "datasette" in cmd
                assert "serve" in cmd
                assert "127.0.0.1" in cmd
                assert "9999" in cmd
                assert "--template-dir" in cmd
                assert "--setting" in cmd
                assert "sql_time_limit_ms" in cmd
                assert "15000" in cmd
            finally:
                CaseConfig.output_dir = property(original_output_dir)
                CaseConfig.db_path = property(original_db_path)

    @patch("casestack.cli.subprocess.run")
    @patch("casestack.cli._load_case")
    def test_serve_immutable_mode(self, mock_load_case, mock_subprocess_run):
        """Serve with --immutable should pass -i flag to datasette."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            case, db_path = self._make_case_with_db(tmpdir)

            original_output_dir = CaseConfig.output_dir.fget
            original_db_path = CaseConfig.db_path.fget
            CaseConfig.output_dir = property(lambda self: tmpdir / "output" / "test-case")
            CaseConfig.db_path = property(lambda self: tmpdir / "output" / "test-case" / "test-case.db")

            mock_load_case.return_value = case

            try:
                from click.testing import CliRunner

                from casestack.cli import cli

                runner = CliRunner()
                result = runner.invoke(cli, ["serve", "--immutable"])

                assert mock_subprocess_run.called, "subprocess.run was not called"
                cmd = mock_subprocess_run.call_args[0][0]

                # In immutable mode, -i should precede the db path
                assert "-i" in cmd, "Missing -i flag for immutable mode"
                # The db path should follow -i
                i_index = cmd.index("-i")
                assert str(db_path) in cmd[i_index + 1], "Database path should follow -i flag"
            finally:
                CaseConfig.output_dir = property(original_output_dir)
                CaseConfig.db_path = property(original_db_path)

    @patch("casestack.cli.subprocess.run")
    @patch("casestack.cli._load_case")
    def test_serve_includes_metadata(self, mock_load_case, mock_subprocess_run):
        """Serve command should include --metadata when datasette.yaml exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            case, db_path = self._make_case_with_db(tmpdir)

            original_output_dir = CaseConfig.output_dir.fget
            original_db_path = CaseConfig.db_path.fget
            CaseConfig.output_dir = property(lambda self: tmpdir / "output" / "test-case")
            CaseConfig.db_path = property(lambda self: tmpdir / "output" / "test-case" / "test-case.db")

            mock_load_case.return_value = case

            try:
                from click.testing import CliRunner

                from casestack.cli import cli

                runner = CliRunner()
                result = runner.invoke(cli, ["serve"])

                assert mock_subprocess_run.called
                cmd = mock_subprocess_run.call_args[0][0]

                assert "--metadata" in cmd, "Missing --metadata flag"
                metadata_index = cmd.index("--metadata")
                assert "datasette.yaml" in cmd[metadata_index + 1]
            finally:
                CaseConfig.output_dir = property(original_output_dir)
                CaseConfig.db_path = property(original_db_path)

    @patch("casestack.cli.subprocess.run")
    @patch("casestack.cli._load_case")
    def test_serve_default_port_from_case(self, mock_load_case, mock_subprocess_run):
        """Serve should use case.serve_port when --port is not specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            case, db_path = self._make_case_with_db(tmpdir)
            case.serve_port = 7777

            original_output_dir = CaseConfig.output_dir.fget
            original_db_path = CaseConfig.db_path.fget
            CaseConfig.output_dir = property(lambda self: tmpdir / "output" / "test-case")
            CaseConfig.db_path = property(lambda self: tmpdir / "output" / "test-case" / "test-case.db")

            mock_load_case.return_value = case

            try:
                from click.testing import CliRunner

                from casestack.cli import cli

                runner = CliRunner()
                result = runner.invoke(cli, ["serve"])

                assert mock_subprocess_run.called
                cmd = mock_subprocess_run.call_args[0][0]

                assert "7777" in cmd, "Default port from case config not used"
            finally:
                CaseConfig.output_dir = property(original_output_dir)
                CaseConfig.db_path = property(original_db_path)
