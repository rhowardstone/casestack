"""CaseStack CLI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()

BANNER = """
[bold cyan]CaseStack[/bold cyan] — Document Intelligence Platform
[dim]Turn any document dump into a searchable evidence database[/dim]
"""


def _load_case(case_path: str | None) -> "CaseConfig":
    from casestack.case import CaseConfig

    if case_path:
        p = Path(case_path)
        if not p.exists():
            console.print(f"[red]Case config not found: {p}[/red]")
            sys.exit(1)
        return CaseConfig.from_yaml(p)
    for default in ["case.yaml", "case.yml"]:
        if Path(default).exists():
            return CaseConfig.from_yaml(Path(default))
    console.print("[red]No case.yaml found. Use --case or create one from case.yaml.example[/red]")
    sys.exit(1)


@click.group()
@click.version_option(package_name="casestack")
def cli():
    """CaseStack — document dump to searchable evidence database."""
    console.print(BANNER)


@cli.command()
@click.argument(
    "documents_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option("--name", "-n", required=True, help="Case name")
@click.option(
    "--case",
    "case_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to case.yaml (overrides --name and documents_dir)",
)
@click.option("--skip-ocr", is_flag=True, help="Skip OCR step")
@click.option("--skip-entities", is_flag=True, help="Skip entity extraction")
@click.option("--skip-dedup", is_flag=True, help="Skip deduplication")
def ingest(documents_dir, name, case_path, skip_ocr, skip_entities, skip_dedup):
    """Ingest a document directory into a searchable database.

    \b
    Examples:
      casestack ingest ./my-pdfs --name "City Council FOIA"
      casestack ingest ./documents --case case.yaml
    """
    if case_path:
        case = _load_case(str(case_path))
    else:
        from casestack.case import CaseConfig

        slug = (
            "".join(c if c.isalnum() or c == "-" else "-" for c in name.lower())[:40].strip("-")
        )
        case = CaseConfig(name=name, slug=slug, documents_dir=documents_dir)

    from casestack.ingest import run_ingest

    run_ingest(case, skip_ocr=skip_ocr, skip_entities=skip_entities, skip_dedup=skip_dedup)


@cli.command()
@click.option("--case", "case_path", type=click.Path(), default=None)
@click.option("--port", "-p", type=int, default=None)
@click.option("--host", type=str, default="127.0.0.1")
def serve(case_path, port, host):
    """Serve the case database with Datasette.

    \b
    Examples:
      casestack serve
      casestack serve --case case.yaml --port 8080
    """
    case = _load_case(case_path)
    db = case.db_path
    if not db.exists():
        console.print(f"[red]Database not found: {db}[/red]")
        console.print("Run 'casestack ingest' first.")
        sys.exit(1)

    ds_config = case.output_dir / "datasette.yaml"
    serve_port = port or case.serve_port

    cmd = [
        sys.executable,
        "-m",
        "datasette",
        "serve",
        str(db),
        "-h",
        host,
        "-p",
        str(serve_port),
    ]
    if ds_config.exists():
        cmd.extend(["--metadata", str(ds_config)])

    console.print(f"[bold]Serving[/bold] {db.name} at http://{host}:{serve_port}")
    subprocess.run(cmd)


@cli.command()
@click.option("--case", "case_path", type=click.Path(), default=None)
def status(case_path):
    """Show case status."""
    case = _load_case(case_path)
    db = case.db_path

    console.print(f"\n[bold]{case.name}[/bold] ({case.slug})")
    console.print(f"  Documents dir: {case.documents_dir}")
    console.print(f"  Output dir:    {case.output_dir}")

    if db.exists():
        size_mb = db.stat().st_size / 1_000_000
        console.print(f"  Database:      {db} ({size_mb:.1f} MB)")

        import sqlite3

        conn = sqlite3.connect(str(db))
        try:
            count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            console.print(f"  Documents:     {count:,}")
        except Exception:
            pass
        finally:
            conn.close()
    else:
        console.print("  [yellow]Not yet ingested. Run: casestack ingest[/yellow]")
