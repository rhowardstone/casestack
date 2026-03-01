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
    *,
    skip_overrides: dict[str, bool] | None = None,
) -> Path:
    """Run the full ingest pipeline. Returns path to output SQLite DB.

    Args:
        case: Case configuration.
        skip_overrides: Optional dict of step_id -> enabled to override
            pipeline defaults and case.yaml settings.
    """

    def _enabled(step_id: str) -> bool:
        if skip_overrides and step_id in skip_overrides:
            return skip_overrides[step_id]
        return case.is_step_enabled(step_id)

    settings = Settings.from_case(case)
    settings.ensure_dirs()

    ocr_dir = settings.output_dir / "ocr"
    entities_dir = settings.output_dir / "entities"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    entities_dir.mkdir(parents=True, exist_ok=True)

    transcripts_collected: list = []  # Transcript objects for SQLite export
    captions_collected: list = []  # PageCaption objects for SQLite export
    images_collected: list = []  # ExtractedImage objects for SQLite export

    console.print(f"\n[bold cyan]CaseStack[/bold cyan] — Ingesting: {case.name}")
    console.print(f"  Documents: {case.documents_dir}")
    console.print(f"  Output:    {settings.output_dir}")

    # --- Step 1: OCR ---
    if _enabled("ocr"):
        pdfs = sorted(case.documents_dir.rglob("*.pdf"))
        total_pdfs = len(pdfs)
        console.print(f"\n[bold]Step 1: OCR[/bold] — {total_pdfs:,} PDFs")
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
        console.print("\n[dim]Step 1: OCR — disabled[/dim]")

    # --- Step 1b: Transcription (audio/video) ---
    if _enabled("transcription"):
        from casestack.processors.transcription import MEDIA_EXTENSIONS

        media_files = sorted(
            f
            for f in case.documents_dir.rglob("*")
            if f.suffix.lower() in MEDIA_EXTENSIONS and f.is_file()
        )
        if media_files:
            console.print(f"\n[bold]Step 1b: Transcription[/bold] — {len(media_files):,} media files")
            try:
                import faster_whisper as _fw  # noqa: F401

                from casestack.processors.transcription import TranscriptionProcessor

                tp = TranscriptionProcessor(settings)
                t_results = tp.process_batch(media_files, settings.output_dir)

                ok = 0
                for tr in t_results:
                    if tr.document is not None:
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
            console.print("\n[dim]Step 1b: Transcription — no media files found[/dim]")
    else:
        console.print("\n[dim]Step 1b: Transcription — disabled[/dim]")

    # --- Step 1c: Document conversion (office/text/other) ---
    if _enabled("doc_conversion"):
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
                f"\n[bold]Step 1c: Document conversion[/bold]"
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
                "\n[dim]Step 1c: Document conversion — no additional files found[/dim]"
            )
    else:
        console.print("\n[dim]Step 1c: Document conversion — disabled[/dim]")

    # --- Step 1d: Image captioning (optional) ---
    if _enabled("page_captions"):
        try:
            import torch as _torch  # noqa: F401

            from casestack.processors.captioner import CaptionProcessor

            ocr_jsons = list(ocr_dir.glob("*.json"))
            if ocr_jsons:
                console.print(f"\n[bold]Step 1d: Page captions[/bold]")
                cp = CaptionProcessor(settings, model_name=case.caption_model)
                captions_collected = cp.process_batch(
                    ocr_dir=ocr_dir,
                    documents_dir=case.documents_dir,
                    output_dir=settings.output_dir,
                    char_threshold=case.caption_char_threshold,
                )
                console.print(f"  [green]{len(captions_collected):,} page captions generated[/green]")
            else:
                console.print("\n[dim]Step 1d: Page captions — no OCR output to scan[/dim]")
        except ImportError:
            console.print(
                "\n[dim]Step 1d: Page captions — skipped"
                " (install with: pip install 'casestack[captioning]')[/dim]"
            )
    else:
        console.print("\n[dim]Step 1d: Page captions — disabled[/dim]")

    # --- Step 1e: Image extraction from PDFs ---
    if _enabled("image_extraction"):
        pdfs = sorted(case.documents_dir.rglob("*.pdf"))
        if pdfs:
            console.print(f"\n[bold]Step 1e: Image extraction[/bold] — {len(pdfs):,} PDFs")
            from casestack.models.forensics import ExtractedImage

            images_dir = settings.output_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            min_size = case.caption_min_image_size
            min_bytes = case.image_min_bytes
            page_scan_ratio = case.image_page_scan_ratio

            # Read OCR JSON to get doc_id for each PDF
            _pdf_doc_ids: dict[str, str] = {}
            for jf in ocr_dir.glob("*.json"):
                try:
                    raw = json.loads(jf.read_text(encoding="utf-8"))
                    doc_data = raw.get("document") or raw
                    source = raw.get("source_path", "")
                    doc_id = doc_data.get("id", "")
                    if source and doc_id:
                        _pdf_doc_ids[Path(source).name] = doc_id
                    if doc_id:
                        _pdf_doc_ids[jf.stem] = doc_id
                except Exception:
                    continue

            # Build work items: (pdf_path, doc_id, doc_img_dir)
            work_items = []
            for pdf_path in pdfs:
                doc_id = _pdf_doc_ids.get(pdf_path.name) or _pdf_doc_ids.get(pdf_path.stem, pdf_path.stem)
                doc_img_dir = images_dir / doc_id
                # Resume: skip if already extracted
                if doc_img_dir.exists() and any(doc_img_dir.glob("*.png")):
                    for png in sorted(doc_img_dir.glob("*.png")):
                        try:
                            from PIL import Image as _PILImage
                            im = _PILImage.open(png)
                            w, h = im.size
                            im.close()
                        except Exception:
                            continue
                        images_collected.append(ExtractedImage(
                            document_id=doc_id,
                            page_number=int(png.stem.split("_")[0].lstrip("p") or 0),
                            image_index=int(png.stem.split("_")[1]) if "_" in png.stem else 0,
                            width=w,
                            height=h,
                            format="png",
                            file_path=str(png),
                            size_bytes=png.stat().st_size,
                        ))
                else:
                    work_items.append((pdf_path, doc_id, doc_img_dir))

            if work_items:
                resumed = len(images_collected)
                if resumed:
                    console.print(f"  [dim]{resumed:,} images already extracted (resume)[/dim]")

                from concurrent.futures import ProcessPoolExecutor, as_completed

                max_workers = min(case.ocr_workers, 8)
                new_count = 0
                skipped_small = 0
                skipped_pagescan = 0

                with ProcessPoolExecutor(max_workers=max_workers) as pool:
                    futures = {
                        pool.submit(
                            _extract_images_worker,
                            pdf_path, doc_id, doc_img_dir, min_size,
                            min_bytes, page_scan_ratio,
                        ): doc_id
                        for pdf_path, doc_id, doc_img_dir in work_items
                    }
                    for future in as_completed(futures):
                        try:
                            result = future.result()
                            images_collected.extend(result["images"])
                            new_count += result["new"]
                            skipped_small += result["skipped_small"]
                            skipped_pagescan += result["skipped_pagescan"]
                        except Exception:
                            pass

                console.print(f"  [green]{new_count:,} images extracted[/green]")
                if skipped_pagescan:
                    console.print(f"  [dim]{skipped_pagescan:,} full-page scans skipped[/dim]")
                if skipped_small:
                    console.print(f"  [dim]{skipped_small:,} tiny/decorative images skipped[/dim]")
            console.print(f"  [green]Total: {len(images_collected):,} images[/green]")
        else:
            console.print("\n[dim]Step 1e: Image extraction — no PDFs found[/dim]")
    else:
        console.print("\n[dim]Step 1e: Image extraction — disabled[/dim]")

    # --- Step 1f: Image analysis (optional, requires torch) ---
    if _enabled("image_analysis") and images_collected:
        try:
            import torch as _torch  # noqa: F401

            from casestack.processors.captioner import CaptionProcessor as _CP

            console.print(f"\n[bold]Step 1f: Image analysis[/bold] — {len(images_collected):,} images")
            cp = _CP(settings, model_name=case.image_analysis_model)
            images_collected = cp.analyze_images(
                images=images_collected,
                output_dir=settings.output_dir,
            )
            described = sum(1 for i in images_collected if i.description)
            console.print(f"  [green]{described:,} images analyzed[/green]")
        except ImportError:
            console.print(
                "\n[dim]Step 1f: Image analysis — skipped"
                " (install with: pip install 'casestack[captioning]')[/dim]"
            )
    elif not _enabled("image_analysis"):
        console.print("\n[dim]Step 1f: Image analysis — disabled[/dim]")
    else:
        console.print("\n[dim]Step 1f: Image analysis — no extracted images[/dim]")

    # --- Step 1g: Redaction analysis (optional) ---
    if _enabled("redaction_analysis"):
        pdfs = sorted(case.documents_dir.rglob("*.pdf"))
        if pdfs:
            console.print(f"\n[bold]Step 1g: Redaction analysis[/bold] — {len(pdfs):,} PDFs")
            from casestack.processors.redaction import RedactionAnalyzer

            analyzer = RedactionAnalyzer()
            redaction_results = analyzer.analyze_batch(
                pdfs,
                settings.output_dir / "redactions",
                max_workers=case.redaction_workers,
            )
            total_redactions = sum(r.total_redactions for r in redaction_results)
            recoverable = sum(r.recoverable for r in redaction_results)
            console.print(f"  [green]{total_redactions:,} redactions found ({recoverable:,} recoverable)[/green]")
        else:
            console.print("\n[dim]Step 1g: Redaction analysis — no PDFs found[/dim]")
    else:
        console.print("\n[dim]Step 1g: Redaction analysis — disabled[/dim]")

    # --- Step 2: Entity extraction ---
    if _enabled("entities"):
        console.print("\n[bold]Step 2: Entity extraction[/bold]")
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
        console.print("\n[dim]Step 2: Entities — disabled[/dim]")

    # --- Step 3: Dedup ---
    if _enabled("dedup"):
        console.print("\n[bold]Step 3: Deduplication[/bold]")
        source_dir = entities_dir if list(entities_dir.glob("*.json")) else ocr_dir
        json_files = sorted(source_dir.glob("*.json"))
        if json_files:
            import hashlib

            from casestack.processors.dedup import DedupRecord, Deduplicator

            def _dedup_content_hash(text: str) -> str:
                normalised = " ".join(text.lower().split())
                return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

            records: list[DedupRecord] = []
            for jf in json_files:
                try:
                    raw = json.loads(jf.read_text(encoding="utf-8"))
                    doc = raw.get("document") or raw
                    if not (doc.get("id") and doc.get("title")):
                        continue
                    text = doc.get("ocrText", "") or ""
                    records.append(DedupRecord(
                        id=doc["id"],
                        title=doc.get("title", ""),
                        bates_range=doc.get("batesRange"),
                        content_hash=_dedup_content_hash(text) if text.strip() else None,
                    ))
                except Exception:
                    continue

            console.print(f"  [dim]{len(records):,} records loaded (lightweight)[/dim]")
            import logging
            logging.basicConfig(level=logging.INFO, format="  %(message)s")
            deduplicator = Deduplicator(threshold=case.dedup_threshold)
            pairs = deduplicator.find_duplicates(records)
            console.print(f"  [green]{len(pairs)} duplicate pairs found[/green]")

            report_path = settings.output_dir / "dedup-report.json"
            with open(report_path, "w", encoding="utf-8") as f:
                f.write("[\n")
                for idx, p in enumerate(pairs):
                    if idx:
                        f.write(",\n")
                    json.dump(p.model_dump(), f, default=str)
                f.write("\n]\n")
            del pairs, records  # Free memory before SQLite export
    else:
        console.print("\n[dim]Step 3: Dedup — disabled[/dim]")

    # --- Step 4: SQLite export ---
    console.print("\n[bold]Step 4: SQLite export[/bold]")
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
        captions=captions_collected or None,
        images=images_collected or None,
    )
    console.print(f"  [green]Exported {len(documents)} documents, {len(all_pages)} pages -> {db_path}[/green]")

    # --- Step 4b: Embeddings (optional) ---
    if _enabled("embeddings"):
        console.print(f"\n[bold]Step 4b: Semantic embeddings[/bold]")
        try:
            from casestack.processors.embeddings import EmbeddingProcessor

            ep = EmbeddingProcessor(
                settings,
                model_name=case.embedding_model,
                dimensions=case.embedding_dimensions,
            )
            ep.process_batch(documents, settings.output_dir, fmt="sqlite")
            console.print(f"  [green]Embeddings generated for {len(documents):,} documents[/green]")
        except ImportError:
            console.print(
                "  [yellow]sentence-transformers not installed — skipping."
                " Install with: pip install 'casestack[embeddings]'[/yellow]"
            )
    else:
        console.print("\n[dim]Step 4b: Embeddings — disabled[/dim]")

    # --- Step 4c: Knowledge graph (optional) ---
    if _enabled("knowledge_graph"):
        console.print(f"\n[bold]Step 4c: Knowledge graph[/bold]")
        from casestack.processors.knowledge_graph import KnowledgeGraphBuilder

        builder = KnowledgeGraphBuilder()
        builder.add_documents(documents)
        graph = builder.build()
        graph_dir = settings.output_dir / "graph"
        graph_dir.mkdir(parents=True, exist_ok=True)
        KnowledgeGraphBuilder.export_json(graph, graph_dir / "knowledge-graph.json")
        console.print(f"  [green]{graph.node_count} nodes, {graph.edge_count} edges[/green]")
    else:
        console.print("\n[dim]Step 4c: Knowledge graph — disabled[/dim]")

    # --- Generate Datasette config ---
    _generate_datasette_config(case, db_path)

    console.print(f"\n[bold green]Done![/bold green] Serve with:")
    console.print("  casestack serve --case case.yaml")
    console.print(f"  # or: datasette serve {db_path}")

    return db_path


def _extract_images_worker(
    pdf_path: Path,
    doc_id: str,
    doc_img_dir: Path,
    min_size: int,
    min_bytes: int = 5120,
    page_scan_ratio: float = 0.8,
) -> dict:
    """Worker for parallel image extraction. Runs in a subprocess."""
    from casestack.models.forensics import ExtractedImage
    from casestack.processors.pymupdf_extractor import PyMuPdfExtractor

    extractor = PyMuPdfExtractor()
    images: list[ExtractedImage] = []
    new = 0
    skipped_small = 0
    skipped_pagescan = 0

    try:
        page_images = extractor.extract_images(pdf_path)
    except Exception:
        return {"images": [], "new": 0, "skipped_small": 0, "skipped_pagescan": 0}

    if not page_images:
        return {"images": [], "new": 0, "skipped_small": 0, "skipped_pagescan": 0}

    doc_img_dir.mkdir(parents=True, exist_ok=True)
    for pi in page_images:
        if pi.width < min_size or pi.height < min_size:
            skipped_small += 1
            continue
        if len(pi.image_bytes) < min_bytes:
            skipped_small += 1
            continue
        if pi.page_width and pi.page_height:
            page_area = pi.page_width * pi.page_height
            img_area = pi.width * pi.height
            if page_area > 0 and img_area / page_area > page_scan_ratio:
                skipped_pagescan += 1
                continue

        fname = f"p{pi.page_number}_{pi.image_index}.png"
        img_path = doc_img_dir / fname
        img_path.write_bytes(pi.image_bytes)

        images.append(ExtractedImage(
            document_id=doc_id,
            page_number=pi.page_number,
            image_index=pi.image_index,
            width=pi.width,
            height=pi.height,
            format="png",
            file_path=str(img_path),
            size_bytes=len(pi.image_bytes),
        ))
        new += 1

    return {
        "images": images,
        "new": new,
        "skipped_small": skipped_small,
        "skipped_pagescan": skipped_pagescan,
    }


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
