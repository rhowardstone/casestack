"""Orchestrate the full ingest pipeline: scan -> OCR -> entities -> dedup -> export."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml
from rich.console import Console

from casestack.case import CaseConfig
from casestack.config import Settings

console = Console()
logger = logging.getLogger(__name__)


@runtime_checkable
class IngestCallback(Protocol):
    """Protocol for receiving ingest progress events."""

    def on_step_start(self, step_id: str, total: int) -> None: ...
    def on_step_progress(self, step_id: str, current: int, total: int) -> None: ...
    def on_step_complete(self, step_id: str, stats: dict) -> None: ...
    def on_log(self, message: str, level: str) -> None: ...
    def on_complete(self, stats: dict) -> None: ...
    def on_error(self, step_id: str, message: str) -> None: ...


def run_ingest(
    case: CaseConfig,
    *,
    skip_overrides: dict[str, bool] | None = None,
    callback: IngestCallback | None = None,
) -> Path:
    """Run the full ingest pipeline. Returns path to output SQLite DB.

    Args:
        case: Case configuration.
        skip_overrides: Optional dict of step_id -> enabled to override
            pipeline defaults and case.yaml settings.
        callback: Optional callback for receiving progress events.
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
    entities_collected: list = []  # ExtractedEntity objects for SQLite export

    console.print(f"\n[bold cyan]CaseStack[/bold cyan] — Ingesting: {case.name}")
    console.print(f"  Documents: {case.documents_dir}")
    console.print(f"  Output:    {settings.output_dir}")
    if callback:
        callback.on_log(f"Ingesting: {case.name}", "info")

    def _handle_step_error(step_id: str, exc: Exception) -> None:
        console.print(f"  [red]{step_id} failed: {exc}[/red]")
        if callback:
            callback.on_log(f"{step_id} failed: {exc}", "error")
            callback.on_step_complete(step_id, {"failed": True, "error": str(exc)})

    # --- Step 1: OCR ---
    if _enabled("ocr"):
        pdfs = sorted(case.documents_dir.rglob("*.pdf"))
        total_pdfs = len(pdfs)
        console.print(f"\n[bold]Step 1: OCR[/bold] — {total_pdfs:,} PDFs")
        if callback:
            callback.on_step_start("ocr", total_pdfs)
        try:
            if pdfs:
                from casestack.processors.ocr import OcrProcessor

                processor = OcrProcessor(settings, backend=case.ocr_backend)

                # Check how many are already done before batching
                already_done = sum(1 for _ in ocr_dir.glob("*.json"))
                if already_done:
                    console.print(f"  [dim]{already_done:,} already processed (resume)[/dim]")

                # Use smaller batches so live progress is visible on medium runs (e.g. ~100 PDFs).
                batch_size = 25 if total_pdfs <= 1000 else 500
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
                    if callback:
                        callback.on_step_progress(
                            "ocr",
                            min(batch_start + len(batch), total_pdfs),
                            total_pdfs,
                        )
                    del results  # Free memory between batches
                if ok:
                    console.print(f"  [green]{ok:,} newly processed[/green]")
                total_docs = sum(1 for _ in ocr_dir.glob('*.json'))
                console.print(f"  [green]Total: {total_docs:,} documents[/green]")
                if callback:
                    callback.on_step_complete("ocr", {"processed": ok, "total": total_docs})
            else:
                # Text files (.txt, .md, .csv, .html) are handled by Step 1c
                # (markitdown) when doc_conversion is enabled.  Only fall back
                # to the simple text ingestion when markitdown is disabled too,
                # to avoid producing duplicate documents for the same file.
                if not _enabled("doc_conversion"):
                    console.print("  [yellow]No PDFs found, scanning for text files...[/yellow]")
                    _ingest_text_files(case.documents_dir, ocr_dir)
                    if callback:
                        callback.on_step_complete("ocr", {"processed": 0, "fallback": "text_files"})
                else:
                    console.print("  [dim]No PDFs — text/office files handled by Step 1c[/dim]")
                    if callback:
                        callback.on_step_complete("ocr", {"processed": 0})
        except Exception as exc:
            _handle_step_error("ocr", exc)
    else:
        console.print("\n[dim]Step 1: OCR — disabled[/dim]")
        if callback:
            callback.on_step_complete("ocr", {"skipped": True})

    # --- Step 1b: Transcription (audio/video) ---
    if _enabled("transcription"):
        from casestack.processors.transcription import MEDIA_EXTENSIONS

        media_files = sorted(
            f
            for f in case.documents_dir.rglob("*")
            if f.suffix.lower() in MEDIA_EXTENSIONS and f.is_file()
        )
        if callback:
            callback.on_step_start("transcription", len(media_files) if media_files else 0)
        if media_files:
            console.print(f"\n[bold]Step 1b: Transcription[/bold] — {len(media_files):,} media files")
            try:
                import faster_whisper as _fw  # noqa: F401

                from casestack.processors.transcription import TranscriptionProcessor

                tp = TranscriptionProcessor(settings)
                t_results = tp.process_batch(
                    media_files,
                    settings.output_dir,
                    progress_callback=(
                        (lambda current, total: callback.on_step_progress("transcription", current, total))
                        if callback else None
                    ),
                )

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
                if callback:
                    callback.on_step_complete("transcription", {"transcribed": ok})
            except ImportError:
                console.print(
                    "  [yellow]faster-whisper not installed — skipping."
                    " Install with: pip install 'casestack[transcription]'[/yellow]"
                )
                if callback:
                    callback.on_step_complete("transcription", {"skipped": True, "reason": "missing dependency"})
            except Exception as exc:
                _handle_step_error("transcription", exc)
        else:
            console.print("\n[dim]Step 1b: Transcription — no media files found[/dim]")
            if callback:
                callback.on_step_complete("transcription", {"skipped": True, "reason": "no media files"})
    else:
        console.print("\n[dim]Step 1b: Transcription — disabled[/dim]")
        if callback:
            callback.on_step_complete("transcription", {"skipped": True})

    # --- Step 1b2: Email extraction (.eml files) ---
    # Handled separately from markitdown: uses stdlib email module to extract
    # clean text + headers while saving binary attachments as separate files
    # for the image/media pipeline to process.
    if _enabled("doc_conversion"):
        eml_files = sorted(
            f for f in case.documents_dir.rglob("*.eml") if f.is_file()
        )
        if eml_files:
            console.print(f"\n[bold]Step 1b2: Email extraction[/bold] — {len(eml_files):,} .eml files")
            if callback:
                callback.on_step_start("email_extraction", len(eml_files))
            try:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                from casestack.processors.email_extractor import process_eml, _ATTACH_SUBDIR
                from casestack.processors.markitdown_extractor import _content_key

                attach_dir = case.documents_dir / _ATTACH_SUBDIR

                # Filter to only files not yet processed (resume support)
                existing_keys = {f.stem for f in ocr_dir.glob("*.json")}
                to_process = [(p, _content_key(p)) for p in eml_files if _content_key(p) not in existing_keys]
                already_done = len(eml_files) - len(to_process)
                if already_done:
                    console.print(f"  [dim]{already_done:,} already processed (resume)[/dim]")

                ok = already_done
                done_count = already_done

                def _extract_one(args: tuple) -> tuple:
                    eml_path, key = args
                    result = process_eml(eml_path, extract_attachments_to=attach_dir)
                    return key, result

                from casestack.models.forensics import ExtractedImage as _ExtractedImage
                _IMG_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".heic"}

                max_email_workers = min(4, len(to_process)) if to_process else 1
                with ThreadPoolExecutor(max_workers=max_email_workers) as pool:
                    future_map = {pool.submit(_extract_one, item): item for item in to_process}
                    for future in as_completed(future_map):
                        try:
                            key, result = future.result()
                            out_path = ocr_dir / f"{key}.json"
                            out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                            if result.document:
                                ok += 1
                                # Register image attachments in images_collected so they
                                # appear in the Images gallery
                                for warn in result.warnings:
                                    if warn.startswith("Extracted ") and "attachment" in warn:
                                        # Parse extracted attachment paths from warnings
                                        pass  # handled below via attach_dir scan
                        except Exception as exc:
                            logger.warning("Email extraction failed: %s", exc)
                        done_count += 1
                        if callback:
                            callback.on_step_progress("email_extraction", done_count, len(eml_files))

                # Scan extracted attachments and register images in images_collected
                if attach_dir.exists():
                    for img_file in attach_dir.rglob("*"):
                        if img_file.suffix.lower() in _IMG_SUFFIXES and img_file.is_file():
                            try:
                                from PIL import Image as _PilImg
                                w, h = _PilImg.open(img_file).size
                            except Exception:
                                w, h = 0, 0
                            images_collected.append(_ExtractedImage(
                                document_id=img_file.parent.name,  # email stem as doc ref
                                page_number=1,
                                image_index=0,
                                width=w,
                                height=h,
                                format=img_file.suffix.lstrip(".").lower(),
                                file_path=str(img_file),
                                size_bytes=img_file.stat().st_size,
                            ))

                console.print(f"  [green]{ok:,} emails extracted[/green]")
                if callback:
                    callback.on_step_complete("email_extraction", {"extracted": ok})
            except Exception as exc:
                _handle_step_error("email_extraction", exc)

    # --- Step 1c: Document conversion (office/text/other) ---
    if _enabled("doc_conversion"):
        from casestack.processors.markitdown_extractor import (
            IMAGE_EXTENSIONS as _IMG_EXT,
            MARKITDOWN_EXTENSIONS,
        )
        from casestack.processors.transcription import MEDIA_EXTENSIONS as _MEDIA_EXT

        # Exclude anything already handled by other steps (PDF, media, images).
        # Images were previously in MARKITDOWN_EXTENSIONS but only yielded EXIF
        # noise — they now go through the standalone image step (1c-img) instead.
        _handled_extensions = {".pdf"} | _MEDIA_EXT | _IMG_EXT
        doc_convert_files = sorted(
            f
            for f in case.documents_dir.rglob("*")
            if f.suffix.lower() in MARKITDOWN_EXTENSIONS
            and f.suffix.lower() not in _handled_extensions
            and f.is_file()
        )
        if callback:
            callback.on_step_start("doc_conversion", len(doc_convert_files))
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
                if callback:
                    callback.on_step_progress("doc_conversion", len(doc_convert_files), len(doc_convert_files))
                console.print(f"  [green]{ok:,} converted[/green]")
                if callback:
                    callback.on_step_complete("doc_conversion", {"converted": ok})
            except ImportError:
                console.print(
                    "  [yellow]markitdown not installed — skipping."
                    " Install with: pip install 'casestack[documents]'[/yellow]"
                )
                if callback:
                    callback.on_step_complete("doc_conversion", {"skipped": True, "reason": "missing dependency"})
            except Exception as exc:
                _handle_step_error("doc_conversion", exc)
        else:
            console.print(
                "\n[dim]Step 1c: Document conversion — no additional files found[/dim]"
            )
            if callback:
                callback.on_step_complete("doc_conversion", {"skipped": True, "reason": "no files"})
    else:
        console.print("\n[dim]Step 1c: Document conversion — disabled[/dim]")
        if callback:
            callback.on_step_complete("doc_conversion", {"skipped": True})

    # --- Step 1c-img: Standalone image files ---
    # Standalone images (PNG/JPG/etc.) not embedded in PDFs — give them at
    # minimum a stub document entry so they show up in the corpus index.
    # If the captioning extra is available they'll get proper VLM descriptions
    # in Step 1d; this step just ensures they're never silently dropped.
    if _enabled("doc_conversion"):
        from casestack.processors.markitdown_extractor import (
            IMAGE_EXTENSIONS as _IMG_EXT2,
            process_single_image_stub,
        )
        from casestack.processors.transcription import MEDIA_EXTENSIONS as _MEDIA_EXT2

        standalone_images = sorted(
            f
            for f in case.documents_dir.rglob("*")
            if f.suffix.lower() in _IMG_EXT2
            and f.suffix.lower() not in _MEDIA_EXT2
            and f.is_file()
        )
        if standalone_images:
            console.print(
                f"\n[bold]Step 1c-img: Standalone images[/bold]"
                f" — {len(standalone_images):,} image files"
            )
            img_ok = 0
            for img_path in standalone_images:
                try:
                    from casestack.processors.markitdown_extractor import _content_key
                    key = _content_key(img_path)
                    out_path = ocr_dir / f"{key}.json"
                    if out_path.exists():
                        continue
                    result = process_single_image_stub(img_path)
                    out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                    img_ok += 1
                except Exception as exc:
                    logger.warning("Image stub failed for %s: %s", img_path.name, exc)
            console.print(f"  [green]{img_ok:,} image stubs created[/green]")

    # --- Step 1d: Image captioning (optional) ---
    if _enabled("page_captions"):
        ocr_jsons = list(ocr_dir.glob("*.json"))
        if callback:
            callback.on_step_start("page_captions", len(ocr_jsons))
        try:
            import torch as _torch  # noqa: F401

            from casestack.processors.captioner import CaptionProcessor

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
                if callback:
                    callback.on_step_progress("page_captions", len(ocr_jsons), len(ocr_jsons))
                    callback.on_step_complete("page_captions", {"captions": len(captions_collected)})
            else:
                console.print("\n[dim]Step 1d: Page captions — no OCR output to scan[/dim]")
                if callback:
                    callback.on_step_complete("page_captions", {"skipped": True, "reason": "no OCR output"})
        except ImportError:
            console.print(
                "\n[dim]Step 1d: Page captions — skipped"
                " (install with: pip install 'casestack[captioning]')[/dim]"
            )
            if callback:
                callback.on_step_complete("page_captions", {"skipped": True, "reason": "missing dependency"})
        except Exception as exc:
            _handle_step_error("page_captions", exc)
    else:
        console.print("\n[dim]Step 1d: Page captions — disabled[/dim]")
        if callback:
            callback.on_step_complete("page_captions", {"skipped": True})

    # --- Step 1e: Image extraction from PDFs ---
    if _enabled("image_extraction"):
        pdfs = sorted(case.documents_dir.rglob("*.pdf"))
        if callback:
            callback.on_step_start("image_extraction", len(pdfs))
        if pdfs:
            try:
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
                    resumed = len(pdfs) - len(work_items)
                    if resumed:
                        console.print(f"  [dim]{resumed:,} PDFs already extracted (resume)[/dim]")
                        if callback:
                            callback.on_step_progress("image_extraction", resumed, len(pdfs))

                    from concurrent.futures import ProcessPoolExecutor, as_completed

                    max_workers = min(case.ocr_workers, 8)
                    new_count = 0
                    skipped_small = 0
                    skipped_pagescan = 0
                    done = resumed

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
                            done += 1
                            try:
                                result = future.result()
                                images_collected.extend(result["images"])
                                new_count += result["new"]
                                skipped_small += result["skipped_small"]
                                skipped_pagescan += result["skipped_pagescan"]
                            except Exception:
                                pass
                            if callback:
                                callback.on_step_progress("image_extraction", done, len(pdfs))

                    console.print(f"  [green]{new_count:,} images extracted[/green]")
                    if skipped_pagescan:
                        console.print(f"  [dim]{skipped_pagescan:,} full-page scans skipped[/dim]")
                    if skipped_small:
                        console.print(f"  [dim]{skipped_small:,} tiny/decorative images skipped[/dim]")
                elif callback:
                    callback.on_step_progress("image_extraction", len(pdfs), len(pdfs))
                console.print(f"  [green]Total: {len(images_collected):,} images[/green]")
                if callback:
                    callback.on_step_complete("image_extraction", {"images": len(images_collected)})
            except Exception as exc:
                _handle_step_error("image_extraction", exc)
        else:
            console.print("\n[dim]Step 1e: Image extraction — no PDFs found[/dim]")
            if callback:
                callback.on_step_complete("image_extraction", {"skipped": True, "reason": "no PDFs"})
    else:
        console.print("\n[dim]Step 1e: Image extraction — disabled[/dim]")
        if callback:
            callback.on_step_complete("image_extraction", {"skipped": True})

    # --- Step 1f: Image analysis (optional, requires torch) ---
    if callback:
        callback.on_step_start("image_analysis", len(images_collected))
    if _enabled("image_analysis") and images_collected:
        try:
            import torch as _torch  # noqa: F401

            # Auto-skip on CPU-only systems — VLM inference without GPU would take hours
            if not _torch.cuda.is_available() and not (hasattr(_torch.backends, "mps") and _torch.backends.mps.is_available()):
                console.print(
                    "\n[dim]Step 1f: Image analysis — skipped (no GPU detected;"
                    " enable CUDA or MPS for image analysis)[/dim]"
                )
                if callback:
                    callback.on_step_complete("image_analysis", {"skipped": True, "reason": "no GPU"})
            else:
                from casestack.processors.captioner import CaptionProcessor as _CP

                console.print(f"\n[bold]Step 1f: Image analysis[/bold] — {len(images_collected):,} images")
                cp = _CP(settings, model_name=case.image_analysis_model)
                images_collected = cp.analyze_images(
                    images=images_collected,
                    output_dir=settings.output_dir,
                )
                described = sum(1 for i in images_collected if i.description)
                if callback:
                    callback.on_step_progress("image_analysis", len(images_collected), len(images_collected))
                console.print(f"  [green]{described:,} images analyzed[/green]")
                if callback:
                    callback.on_step_complete("image_analysis", {"analyzed": described})
        except ImportError:
            console.print(
                "\n[dim]Step 1f: Image analysis — skipped"
                " (install with: pip install 'casestack[captioning]')[/dim]"
            )
            if callback:
                callback.on_step_complete("image_analysis", {"skipped": True, "reason": "missing dependency"})
        except Exception as exc:
            _handle_step_error("image_analysis", exc)
    elif not _enabled("image_analysis"):
        console.print("\n[dim]Step 1f: Image analysis — disabled[/dim]")
        if callback:
            callback.on_step_complete("image_analysis", {"skipped": True})
    else:
        console.print("\n[dim]Step 1f: Image analysis — no extracted images[/dim]")
        if callback:
            callback.on_step_complete("image_analysis", {"skipped": True, "reason": "no images"})

    # --- Step 1g: Redaction analysis (optional) ---
    if _enabled("redaction_analysis"):
        pdfs = sorted(case.documents_dir.rglob("*.pdf"))
        if callback:
            callback.on_step_start("redaction_analysis", len(pdfs))
        if pdfs:
            try:
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
                if callback:
                    callback.on_step_progress("redaction_analysis", len(pdfs), len(pdfs))
                console.print(f"  [green]{total_redactions:,} redactions found ({recoverable:,} recoverable)[/green]")
                if callback:
                    callback.on_step_complete("redaction_analysis", {"redactions": total_redactions, "recoverable": recoverable})
            except Exception as exc:
                _handle_step_error("redaction_analysis", exc)
        else:
            console.print("\n[dim]Step 1g: Redaction analysis — no PDFs found[/dim]")
            if callback:
                callback.on_step_complete("redaction_analysis", {"skipped": True, "reason": "no PDFs"})
    else:
        console.print("\n[dim]Step 1g: Redaction analysis — disabled[/dim]")
        if callback:
            callback.on_step_complete("redaction_analysis", {"skipped": True})

    # --- Step 2: Entity extraction ---
    if _enabled("entities"):
        console.print("\n[bold]Step 2: Entity extraction[/bold]")
        json_files = sorted(ocr_dir.glob("*.json"))
        if callback:
            callback.on_step_start("entities", len(json_files))
        if json_files:
            try:
                from casestack.models.document import ProcessingResult
                from casestack.models.forensics import ExtractedEntity as _FEntity
                from casestack.processors.entities import EntityExtractor

                # Load registry if configured (optional — NER runs without one too)
                registry = None
                registry_path = case.registry_path
                if registry_path and Path(registry_path).exists():
                    from casestack.models.registry import PersonRegistry
                    registry = PersonRegistry.from_json(Path(registry_path))
                    console.print(f"  Registry: {len(registry)} persons")
                else:
                    console.print("  [dim]No registry — running auto-NER (PERSON, ORG, GPE, EMAIL, PHONE)[/dim]")

                entity_types = set(case.entity_types) if case.entity_types else {
                    "PERSON", "ORG", "GPE", "LOC", "EMAIL_ADDR", "PHONE"
                }
                extractor = EntityExtractor(settings, registry, entity_types=entity_types)

                person_link_count = 0
                entity_mention_count = 0
                for i, jf in enumerate(json_files):
                    try:
                        result = ProcessingResult.model_validate_json(
                            jf.read_text(encoding="utf-8")
                        )
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
                        text = "\n".join(text_parts)
                        extraction = extractor.extract_all(text)
                        result.document.personIds = extraction.person_ids
                        person_link_count += len(extraction.person_ids)
                        # Convert to forensics model for SQLite export
                        for ent in extraction.entities:
                            entities_collected.append(_FEntity(
                                document_id=result.document.id,
                                entity_type=ent.label,
                                text=ent.text,
                                confidence=0.85,
                                person_id=ent.person_id,
                            ))
                            entity_mention_count += 1
                        (entities_dir / jf.name).write_text(
                            result.model_dump_json(indent=2), encoding="utf-8"
                        )
                    except Exception:
                        continue
                    finally:
                        if callback:
                            callback.on_step_progress("entities", i + 1, len(json_files))
                console.print(
                    f"  [green]{entity_mention_count:,} entity mentions, "
                    f"{person_link_count} person links[/green]"
                )
                if callback:
                    callback.on_step_complete("entities", {
                        "entity_mentions": entity_mention_count,
                        "entity_links": person_link_count,
                    })
            except Exception as exc:
                _handle_step_error("entities", exc)
                # Copy OCR output to entities dir so downstream steps find it
                for jf in sorted(ocr_dir.glob("*.json")):
                    (entities_dir / jf.name).write_text(
                        jf.read_text(encoding="utf-8"), encoding="utf-8"
                    )
        else:
            console.print("  [yellow]No OCR output to extract from[/yellow]")
            if callback:
                callback.on_step_complete("entities", {"skipped": True, "reason": "no OCR output"})
    else:
        console.print("\n[dim]Step 2: Entities — disabled[/dim]")
        if callback:
            callback.on_step_complete("entities", {"skipped": True})

    # --- Step 3: Dedup ---
    if _enabled("dedup"):
        console.print("\n[bold]Step 3: Deduplication[/bold]")
        source_dir = entities_dir if list(entities_dir.glob("*.json")) else ocr_dir
        json_files = sorted(source_dir.glob("*.json"))
        if callback:
            callback.on_step_start("dedup", len(json_files))
        if json_files:
            try:
                import hashlib

                from casestack.processors.dedup import DedupRecord, Deduplicator

                def _dedup_content_hash(text: str) -> str:
                    normalised = " ".join(text.lower().split())
                    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

                records: list[DedupRecord] = []
                for i, jf in enumerate(json_files):
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
                    finally:
                        if callback:
                            callback.on_step_progress("dedup", i + 1, len(json_files))

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
                if callback:
                    callback.on_step_complete("dedup", {"duplicate_pairs": len(pairs)})
                del pairs, records  # Free memory before SQLite export
            except Exception as exc:
                _handle_step_error("dedup", exc)
        else:
            if callback:
                callback.on_step_complete("dedup", {"skipped": True, "reason": "no OCR output"})
    else:
        console.print("\n[dim]Step 3: Dedup — disabled[/dim]")
        if callback:
            callback.on_step_complete("dedup", {"skipped": True})

    # --- Step 4: SQLite export ---
    console.print("\n[bold]Step 4: SQLite export[/bold]")
    source_dir = entities_dir if list(entities_dir.glob("*.json")) else ocr_dir
    json_files = sorted(source_dir.glob("*.json"))
    if callback:
        callback.on_step_start("sqlite_export", len(json_files))

    from casestack.exporters.sqlite_export import SqliteExporter
    from casestack.models.document import Document, Page, ProcessingResult

    documents = []
    all_pages: list[Page] = []
    total_json_files = len(json_files)
    for i, jf in enumerate(json_files):
        try:
            raw = json.loads(jf.read_text(encoding="utf-8"))
            if "document" in raw and raw["document"] is not None:
                result = ProcessingResult.model_validate(raw)
                if result.document:
                    # Propagate the source file path so the DB file_path column
                    # is populated for PDF inline viewing.
                    if result.source_path and not result.document.pdfUrl:
                        result.document.pdfUrl = result.source_path
                    documents.append(result.document)
                    all_pages.extend(result.pages)
            elif "id" in raw and "title" in raw:
                documents.append(Document.model_validate(raw))
        except Exception:
            continue
        finally:
            if callback:
                callback.on_step_progress("sqlite_export", i + 1, total_json_files)

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
        entities=entities_collected or None,
    )
    console.print(f"  [green]Exported {len(documents)} documents, {len(all_pages)} pages -> {db_path}[/green]")
    if callback:
        callback.on_step_complete("sqlite_export", {"documents": len(documents), "pages": len(all_pages)})

    # --- Step 4b: Embeddings (optional) ---
    if _enabled("embeddings"):
        console.print(f"\n[bold]Step 4b: Semantic embeddings[/bold]")
        if callback:
            callback.on_step_start("embeddings", len(documents))
        try:
            from casestack.processors.embeddings import EmbeddingProcessor

            ep = EmbeddingProcessor(
                settings,
                model_name=case.embedding_model,
                dimensions=case.embedding_dimensions,
            )
            ep.process_batch(documents, settings.output_dir, fmt="sqlite")
            if callback:
                callback.on_step_progress("embeddings", len(documents), len(documents))
            console.print(f"  [green]Embeddings generated for {len(documents):,} documents[/green]")
            if callback:
                callback.on_step_complete("embeddings", {"documents": len(documents)})
        except ImportError:
            console.print(
                "  [yellow]sentence-transformers not installed — skipping."
                " Install with: pip install 'casestack[embeddings]'[/yellow]"
            )
            if callback:
                callback.on_step_complete("embeddings", {"skipped": True, "reason": "missing dependency"})
        except Exception as exc:
            _handle_step_error("embeddings", exc)
    else:
        console.print("\n[dim]Step 4b: Embeddings — disabled[/dim]")
        if callback:
            callback.on_step_complete("embeddings", {"skipped": True})

    # --- Step 4c: Knowledge graph (optional) ---
    if _enabled("knowledge_graph"):
        console.print(f"\n[bold]Step 4c: Knowledge graph[/bold]")
        if callback:
            callback.on_step_start("knowledge_graph", len(documents))
        try:
            from casestack.processors.knowledge_graph import KnowledgeGraphBuilder

            builder = KnowledgeGraphBuilder()
            builder.add_documents(documents)
            graph = builder.build()
            graph_dir = settings.output_dir / "graph"
            graph_dir.mkdir(parents=True, exist_ok=True)
            KnowledgeGraphBuilder.export_json(graph, graph_dir / "knowledge-graph.json")
            if callback:
                callback.on_step_progress("knowledge_graph", len(documents), len(documents))
            console.print(f"  [green]{graph.node_count} nodes, {graph.edge_count} edges[/green]")
            if callback:
                callback.on_step_complete("knowledge_graph", {"nodes": graph.node_count, "edges": graph.edge_count})
        except Exception as exc:
            _handle_step_error("knowledge_graph", exc)
    else:
        console.print("\n[dim]Step 4c: Knowledge graph — disabled[/dim]")
        if callback:
            callback.on_step_complete("knowledge_graph", {"skipped": True})

    # --- Generate Datasette config ---
    _generate_datasette_config(case, db_path)

    console.print(f"\n[bold green]Done![/bold green] Serve with:")
    console.print("  casestack serve --case case.yaml")
    console.print(f"  # or: datasette serve {db_path}")

    if callback:
        callback.on_complete({"db_path": str(db_path), "documents": len(documents), "pages": len(all_pages)})

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
