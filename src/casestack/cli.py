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
@click.option("--immutable", "-i", is_flag=True, help="Open database in immutable (read-only) mode")
def serve(case_path, port, host, immutable):
    """Serve the case database with Datasette.

    \b
    Examples:
      casestack serve
      casestack serve --case case.yaml --port 8080
      casestack serve --immutable
    """
    case = _load_case(case_path)
    db = case.db_path
    if not db.exists():
        console.print(f"[red]Database not found: {db}[/red]")
        console.print("Run 'casestack ingest' first.")
        sys.exit(1)

    ds_config = case.output_dir / "datasette.yaml"
    serve_port = port or case.serve_port

    # Locate bundled templates directory
    import importlib.resources

    templates_dir = importlib.resources.files("casestack") / "templates"

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
        "--setting",
        "sql_time_limit_ms",
        "15000",
    ]

    if templates_dir.is_dir():
        cmd.extend(["--template-dir", str(templates_dir)])

    if ds_config.exists():
        cmd.extend(["--metadata", str(ds_config)])

    if immutable:
        # Replace the plain db path with -i flag for immutable mode
        db_index = cmd.index(str(db))
        cmd[db_index:db_index + 1] = ["-i", str(db)]

    console.print(f"[bold]Serving[/bold] {db.name} at http://{host}:{serve_port}")
    if immutable:
        console.print("  [dim]Immutable mode (read-only)[/dim]")
    subprocess.run(cmd)


@cli.command(name="ask")
@click.argument("question")
@click.option("--case", "case_path", type=click.Path(), default=None)
@click.option("--api-key", envvar="OPENROUTER_API_KEY", default=None, help="LLM API key")
def ask_cmd(question, case_path, api_key):
    """Ask a question about the document corpus.

    \b
    Examples:
      casestack ask "What financial connections exist?"
      casestack ask "Who traveled together?" --case case.yaml
      casestack ask "Wire transfers over 100k" --api-key sk-...
    """
    import asyncio

    from casestack.ask import ask

    case = _load_case(case_path)
    db = case.db_path
    if not db.exists():
        console.print("[red]Database not found. Run 'casestack ingest' first.[/red]")
        sys.exit(1)

    with console.status("[bold cyan]Thinking...[/bold cyan]"):
        answer = asyncio.run(ask(question, db, api_key=api_key))

    console.print(f"\n{answer}")


@cli.command("scan-pii")
@click.option("--case", "case_path", type=click.Path(), default=None)
@click.option("--min-confidence", type=float, default=0.7)
def scan_pii(case_path, min_confidence):
    """Scan the database for personally identifiable information."""
    from casestack.pii import scan_database

    case = _load_case(case_path)
    db = case.db_path
    if not db.exists():
        console.print("[red]Database not found. Run 'casestack ingest' first.[/red]")
        sys.exit(1)

    result = scan_database(db)

    # Filter by confidence
    filtered = [m for m in result.matches if m.confidence >= min_confidence]

    console.print(f"\n[bold]PII Scan Results[/bold]")
    console.print(f"  Pages scanned: {result.total_pages_scanned:,}")
    console.print(f"  Matches found: {len(filtered):,} (>= {min_confidence} confidence)")
    console.print(
        f"  Affected pages: {len({(m.doc_id, m.page_number) for m in filtered}):,}"
    )

    by_type: dict[str, int] = {}
    for m in filtered:
        by_type[m.pattern_type] = by_type.get(m.pattern_type, 0) + 1
    for ptype, count in sorted(by_type.items()):
        console.print(f"    {ptype}: {count}")


@cli.command()
@click.option("--case", "case_path", type=click.Path(), default=None)
@click.option("--min-confidence", type=float, default=0.8)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be redacted without changing the database",
)
def redact(case_path, min_confidence, dry_run):
    """Redact PII from the database.

    Scans for PII above the confidence threshold and replaces matches with
    empty strings.  Use --dry-run to preview without modifying data.
    """
    from casestack.pii import redact_database, scan_database

    case = _load_case(case_path)
    db = case.db_path
    if not db.exists():
        console.print("[red]Database not found. Run 'casestack ingest' first.[/red]")
        sys.exit(1)

    result = scan_database(db)
    filtered = [m for m in result.matches if m.confidence >= min_confidence]

    if not filtered:
        console.print("[green]No PII found above confidence threshold.[/green]")
        return

    console.print(f"\n[bold]PII to redact:[/bold] {len(filtered):,} matches")
    by_type: dict[str, int] = {}
    for m in filtered:
        by_type[m.pattern_type] = by_type.get(m.pattern_type, 0) + 1
    for ptype, count in sorted(by_type.items()):
        console.print(f"    {ptype}: {count}")

    if dry_run:
        console.print("\n[yellow]Dry run — no changes made.[/yellow]")
        return

    count = redact_database(db, filtered)
    console.print(f"\n[green]Redacted {count:,} PII items.[/green]")


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
            try:
                page_count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
                console.print(f"  Pages:         {page_count:,}")
            except Exception:
                pass
        except Exception:
            pass
        finally:
            conn.close()
    else:
        console.print("  [yellow]Not yet ingested. Run: casestack ingest[/yellow]")
