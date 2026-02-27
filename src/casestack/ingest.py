"""Orchestrate the full ingest pipeline: scan -> OCR -> entities -> dedup -> export."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from rich.console import Console

from casestack.case import CaseConfig
from casestack.config import Settings

console = Console()


def run_ingest(
    case: CaseConfig,
    skip_ocr: bool = False,
    skip_entities: bool = False,
    skip_dedup: bool = False,
) -> Path:
    """Run the full ingest pipeline. Returns path to output SQLite DB."""

    settings = Settings.from_case(case)
    settings.ensure_dirs()

    ocr_dir = settings.output_dir / "ocr"
    entities_dir = settings.output_dir / "entities"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    entities_dir.mkdir(parents=True, exist_ok=True)

    transcripts_collected: list = []  # Transcript objects for SQLite export

    console.print(f"\n[bold cyan]CaseStack[/bold cyan] — Ingesting: {case.name}")
    console.print(f"  Documents: {case.documents_dir}")
    console.print(f"  Output:    {settings.output_dir}")

    # --- Step 1: OCR ---
    if not skip_ocr:
        pdfs = sorted(case.documents_dir.rglob("*.pdf"))
        total_pdfs = len(pdfs)
        console.print(f"\n[bold]Step 1/5: OCR[/bold] — {total_pdfs:,} PDFs")
        if pdfs:
            from casestack.processors.ocr import OcrProcessor

            processor = OcrProcessor(settings, backend=case.ocr_backend)

            # Check how many are already done before batching
            already_done = sum(1 for _ in ocr_dir.glob("*.json"))
            if already_done:
                console.print(f"  [dim]{already_done:,} already processed (resume)[/dim]")

            # Process in batches to avoid OOM on large corpora
            batch_size = 5000
            ok = 0
            for batch_start in range(0, total_pdfs, batch_size):
                batch = pdfs[batch_start : batch_start + batch_size]
                batch_num = batch_start // batch_size + 1
                total_batches = (total_pdfs + batch_size - 1) // batch_size
                if total_batches > 1:
                    console.print(
                        f"  [dim]Batch {batch_num}/{total_batches}"
                        f" ({batch_start:,}-{batch_start + len(batch):,})[/dim]"
                    )
                results = processor.process_batch(
                    batch, ocr_dir, max_workers=case.ocr_workers
                )
                ok += sum(1 for r in results if r.document is not None)
                del results  # Free memory between batches
            if ok:
                console.print(f"  [green]{ok:,} newly processed[/green]")
            console.print(f"  [green]Total: {sum(1 for _ in ocr_dir.glob('*.json')):,} documents[/green]")
        else:
            console.print("  [yellow]No PDFs found, scanning for text files...[/yellow]")
            _ingest_text_files(case.documents_dir, ocr_dir)
    else:
        console.print("\n[dim]Step 1/5: OCR — skipped[/dim]")

    # --- Step 1b: Transcription (audio/video) ---
    from casestack.processors.transcription import MEDIA_EXTENSIONS

    media_files = sorted(
        f
        for f in case.documents_dir.rglob("*")
        if f.suffix.lower() in MEDIA_EXTENSIONS and f.is_file()
    )
    if media_files:
        console.print(f"\n[bold]Step 1b/5: Transcription[/bold] — {len(media_files):,} media files")
        try:
            import faster_whisper as _fw  # noqa: F401

            from casestack.processors.transcription import TranscriptionProcessor

            tp = TranscriptionProcessor(settings)
            t_results = tp.process_batch(media_files, settings.output_dir)

            ok = 0
            for tr in t_results:
                if tr.document is not None:
                    # Save as OCR-compatible JSON so entity extraction picks it up
                    from casestack.models.document import ProcessingResult

                    compat = ProcessingResult(
                        source_path=tr.source_path,
                        document=tr.document,
                        pages=tr.pages,
                        errors=tr.errors,
                        warnings=tr.warnings,
                        processing_time_ms=tr.processing_time_ms,
                    )
                    out_path = ocr_dir / f"{Path(tr.source_path).stem}.json"
                    out_path.write_text(
                        compat.model_dump_json(indent=2), encoding="utf-8"
                    )
                    ok += 1
                if tr.transcript is not None:
                    transcripts_collected.append(tr.transcript)

            console.print(f"  [green]{ok:,} transcribed[/green]")
        except ImportError:
            console.print(
                "  [yellow]faster-whisper not installed — skipping."
                " Install with: pip install 'casestack[transcription]'[/yellow]"
            )
    else:
        console.print("\n[dim]Step 1b/5: Transcription — no media files found[/dim]")

    # --- Step 1c: Document conversion (office/text/other) ---
    from casestack.processors.markitdown_extractor import MARKITDOWN_EXTENSIONS
    from casestack.processors.transcription import MEDIA_EXTENSIONS as _MEDIA_EXT

    _handled_extensions = {".pdf"} | _MEDIA_EXT
    doc_convert_files = sorted(
        f
        for f in case.documents_dir.rglob("*")
        if f.suffix.lower() in MARKITDOWN_EXTENSIONS
        and f.suffix.lower() not in _handled_extensions
        and f.is_file()
    )
    if doc_convert_files:
        console.print(
            f"\n[bold]Step 1c/5: Document conversion[/bold]"
            f" — {len(doc_convert_files):,} files"
        )
        try:
            import markitdown as _md  # noqa: F401

            from casestack.processors.markitdown_extractor import MarkitdownProcessor

            mp = MarkitdownProcessor(settings)
            m_results = mp.process_batch(doc_convert_files, ocr_dir)
            ok = sum(1 for r in m_results if r.document is not None)
            console.print(f"  [green]{ok:,} converted[/green]")
        except ImportError:
            console.print(
                "  [yellow]markitdown not installed — skipping."
                " Install with: pip install 'casestack[documents]'[/yellow]"
            )
    else:
        console.print(
            "\n[dim]Step 1c/5: Document conversion — no additional files found[/dim]"
        )

    # --- Step 2: Entity extraction ---
    if not skip_entities:
        console.print("\n[bold]Step 2/5: Entity extraction[/bold]")
        json_files = sorted(ocr_dir.glob("*.json"))
        if json_files:
            from casestack.models.document import ProcessingResult

            # EntityExtractor requires a PersonRegistry; only run if we have one.
            registry = None
            registry_path = case.registry_path
            if registry_path and Path(registry_path).exists():
                from casestack.models.registry import PersonRegistry

                registry = PersonRegistry.from_json(Path(registry_path))
                console.print(f"  Registry: {len(registry)} persons")

            if registry is not None:
                from casestack.processors.entities import EntityExtractor

                extractor = EntityExtractor(
                    settings,
                    registry,
                    entity_types=set(case.entity_types),
                )

                count = 0
                for jf in json_files:
                    try:
                        result = ProcessingResult.model_validate_json(
                            jf.read_text(encoding="utf-8")
                        )
                    except Exception:
                        continue
                    if result.document is None:
                        continue
                    text_parts = [
                        t
                        for t in [
                            result.document.title,
                            result.document.summary,
                            result.document.ocrText,
                        ]
                        if t
                    ]
                    extraction = extractor.extract_all("\n".join(text_parts))
                    result.document.personIds = extraction.person_ids
                    count += len(extraction.person_ids)
                    (entities_dir / jf.name).write_text(
                        result.model_dump_json(indent=2), encoding="utf-8"
                    )
                console.print(f"  [green]{count} entity links extracted[/green]")
            else:
                console.print(
                    "  [yellow]No person registry found — skipping entity extraction[/yellow]"
                )
                # Copy OCR output to entities dir so downstream steps find it
                for jf in json_files:
                    (entities_dir / jf.name).write_text(
                        jf.read_text(encoding="utf-8"), encoding="utf-8"
                    )
        else:
            console.print("  [yellow]No OCR output to extract from[/yellow]")
    else:
        console.print("\n[dim]Step 2/5: Entities — skipped[/dim]")

    # --- Step 3: Dedup ---
    if not skip_dedup:
        console.print("\n[bold]Step 3/5: Deduplication[/bold]")
        source_dir = entities_dir if list(entities_dir.glob("*.json")) else ocr_dir
        json_files = sorted(source_dir.glob("*.json"))
        if json_files:
            from casestack.models.document import Document, ProcessingResult
            from casestack.processors.dedup import Deduplicator

            documents: list[Document] = []
            for jf in json_files:
                try:
                    raw = json.loads(jf.read_text(encoding="utf-8"))
                    if "document" in raw and raw["document"] is not None:
                        result = ProcessingResult.model_validate(raw)
                        if result.document:
                            documents.append(result.document)
                    elif "id" in raw and "title" in raw:
                        documents.append(Document.model_validate(raw))
                except Exception:
                    continue

            deduplicator = Deduplicator(threshold=case.dedup_threshold)
            pairs = deduplicator.find_duplicates(documents)
            console.print(f"  [green]{len(pairs)} duplicate pairs found[/green]")

            report_path = settings.output_dir / "dedup-report.json"
            report_path.write_text(
                json.dumps([p.model_dump() for p in pairs], indent=2, default=str),
                encoding="utf-8",
            )
    else:
        console.print("\n[dim]Step 3/5: Dedup — skipped[/dim]")

    # --- Step 4: SQLite export ---
    console.print("\n[bold]Step 4/5: SQLite export[/bold]")
    source_dir = entities_dir if list(entities_dir.glob("*.json")) else ocr_dir
    json_files = sorted(source_dir.glob("*.json"))

    from casestack.exporters.sqlite_export import SqliteExporter
    from casestack.models.document import Document, Page, ProcessingResult

    documents = []
    all_pages: list[Page] = []
    for jf in json_files:
        try:
            raw = json.loads(jf.read_text(encoding="utf-8"))
            if "document" in raw and raw["document"] is not None:
                result = ProcessingResult.model_validate(raw)
                if result.document:
                    documents.append(result.document)
                    all_pages.extend(result.pages)
            elif "id" in raw and "title" in raw:
                documents.append(Document.model_validate(raw))
        except Exception:
            continue

    db_path = case.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    exporter = SqliteExporter()
    exporter.export(
        documents=documents,
        persons=[],
        db_path=db_path,
        pages=all_pages,
        transcripts=transcripts_collected or None,
    )
    console.print(f"  [green]Exported {len(documents)} documents, {len(all_pages)} pages -> {db_path}[/green]")

    # --- Generate Datasette config ---
    _generate_datasette_config(case, db_path)

    console.print(f"\n[bold green]Done![/bold green] Serve with:")
    console.print("  casestack serve --case case.yaml")
    console.print(f"  # or: datasette serve {db_path}")

    return db_path


def _ingest_text_files(docs_dir: Path, ocr_dir: Path) -> None:
    """Fallback: ingest plain text files as pseudo-OCR output."""
    from casestack.models.document import Document, Page, ProcessingResult
    from casestack.utils.hashing import content_hash

    text_files = sorted(
        f
        for f in docs_dir.rglob("*")
        if f.suffix.lower() in (".txt", ".md", ".csv", ".html") and f.is_file()
    )
    for tf in text_files:
        text = tf.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        doc_id = f"txt-{content_hash(text)[:12]}"
        title = tf.stem.replace("_", " ").replace("-", " ").title()
        doc = Document(
            id=doc_id,
            title=title,
            source="local",
            category="other",
            ocrText=text,
            tags=["text-ingest"],
        )
        page = Page(
            document_id=doc_id,
            page_number=1,
            text_content=text,
            char_count=len(text),
        )
        result = ProcessingResult(
            source_path=str(tf),
            document=doc,
            pages=[page],
            processing_time_ms=0,
            errors=[],
        )
        out_path = ocr_dir / f"{doc_id}.json"
        out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    console.print(f"  [green]Ingested {len(text_files)} text files[/green]")


def _generate_datasette_config(case: CaseConfig, db_path: Path) -> None:
    """Generate a datasette.yaml config for this case."""
    config = {
        "title": case.serve_title or f"{case.name} — Document Database",
        "description": case.description,
        "settings": {
            "sql_time_limit_ms": 15000,
            "num_sql_threads": 4,
            "default_page_size": 50,
            "allow_download": False,
            "suggest_facets": False,
            "allow_sql": True,
        },
        "databases": {
            case.slug: {
                "tables": {
                    "documents": {
                        "label_column": "title",
                        "description": "All processed documents",
                    },
                    "pages": {
                        "description": "Per-page text content",
                    },
                    "pages_fts": {
                        "hidden": True,
                    },
                },
            }
        },
    }
    config_path = case.output_dir / "datasette.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")
    console.print(f"  Datasette config: {config_path}")
