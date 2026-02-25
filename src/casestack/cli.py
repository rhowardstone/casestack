"""CaseStack CLI."""
from __future__ import annotations

import click
from rich.console import Console

console = Console()

BANNER = """
[bold cyan]CaseStack[/bold cyan] — Document Intelligence Platform
[dim]Turn any document dump into a searchable evidence database[/dim]
"""


@click.group()
@click.version_option(package_name="casestack")
def cli():
    """CaseStack — document dump to searchable evidence database."""
    console.print(BANNER)
