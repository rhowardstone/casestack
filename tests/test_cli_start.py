"""Tests for the `casestack start` command."""
from __future__ import annotations

import pytest


def test_start_command_exists():
    """The start command is registered."""
    from click.testing import CliRunner
    from casestack.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--help"])
    assert result.exit_code == 0
    assert "Start CaseStack web interface" in result.output


def test_serve_datasette_command_exists():
    """The old serve command is renamed to serve-datasette."""
    from click.testing import CliRunner
    from casestack.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["serve-datasette", "--help"])
    assert result.exit_code == 0
