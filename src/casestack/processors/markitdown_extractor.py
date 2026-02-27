"""Universal document processor using Microsoft markitdown for text extraction."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from casestack.config import Settings
from casestack.models.document import Document, Page, ProcessingResult

logger = logging.getLogger(__name__)

MARKITDOWN_EXTENSIONS = {
    # Office / structured documents
    ".docx", ".xlsx", ".xls", ".pptx",
    # Web / data
    ".html", ".htm", ".csv",
    ".json", ".jsonl",
    # Other formats markitdown handles
    ".epub", ".zip", ".ipynb", ".msg",
    # Plain text
    ".txt", ".md",
    # Images (markitdown extracts EXIF/metadata)
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff",
}


def _process_single_markitdown(args: tuple[str]) -> ProcessingResult:
    """Convert a single file to text via markitdown.

    Module-level function so it can be pickled for ProcessPoolExecutor.
    Accepts ``(file_path,)``.
    """
    (file_path_str,) = args
    path = Path(file_path_str)
    start_ms = time.monotonic_ns() // 1_000_000
    errors: list[str] = []
    warnings: list[str] = []
    md_text = ""

    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    doc_id = f"doc-{content_hash[:12]}"

    try:
        from markitdown import MarkItDown

        converter = MarkItDown()
        result = converter.convert(str(path))
        md_text = result.text_content or ""

        if not md_text.strip():
            warnings.append(f"markitdown produced empty text for {path.name}")
            md_text = ""
    except ImportError:
        errors.append(
            "markitdown not installed. Install with: pip install 'casestack[documents]'"
        )
    except Exception as exc:
        errors.append(f"markitdown conversion failed for {path.name}: {exc}")

    document: Document | None = None
    page_objects: list[Page] = []

    if md_text:
        document = Document(
            id=doc_id,
            title=path.stem.replace("_", " ").replace("-", " ").strip(),
            source="local",
            category="other",
            ocrText=md_text,
            tags=["markitdown"],
        )
        page_objects.append(
            Page(
                document_id=doc_id,
                page_number=1,
                text_content=md_text,
                char_count=len(md_text),
            )
        )
    elif not errors:
        # File produced no text but no errors either — create stub document
        document = Document(
            id=doc_id,
            title=path.stem.replace("_", " ").replace("-", " ").strip(),
            source="local",
            category="other",
            ocrText=None,
            tags=["markitdown"],
        )

    elapsed = (time.monotonic_ns() // 1_000_000) - start_ms
    return ProcessingResult(
        source_path=str(path),
        document=document,
        pages=page_objects,
        errors=errors,
        warnings=warnings,
        processing_time_ms=elapsed,
    )


class MarkitdownProcessor:
    """Process documents through markitdown for universal text extraction."""

    def __init__(self, config: Settings) -> None:
        self.config = config

    def process_file(self, path: Path) -> ProcessingResult:
        """Convert a single file via markitdown."""
        return _process_single_markitdown((str(path),))

    def process_batch(
        self,
        paths: list[Path],
        output_dir: Path,
        max_workers: int = 4,
    ) -> list[ProcessingResult]:
        """Process multiple files with optional parallelism (CPU-only, safe to parallelize).

        Files whose output JSON already exists are skipped (resumable).
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[ProcessingResult] = []

        # Filename-based resume check — existence only, no deserialization
        existing = set(f.stem for f in output_dir.glob("*.json"))
        to_process: list[tuple[Path, str]] = []
        skipped = 0
        for p in paths:
            name_key = p.stem
            if name_key in existing:
                skipped += 1
            else:
                to_process.append((p, name_key))

        if skipped:
            logger.info("markitdown resume: %d already processed, %d new", skipped, len(to_process))

        if not to_process:
            return results

        if max_workers > 1 and len(to_process) > 1:
            results.extend(self._process_parallel(to_process, output_dir, max_workers))
        else:
            results.extend(self._process_sequential(to_process, output_dir))

        return results

    def _process_parallel(
        self,
        to_process: list[tuple[Path, str]],
        output_dir: Path,
        max_workers: int,
    ) -> list[ProcessingResult]:
        """Process files in parallel using ProcessPoolExecutor."""
        from concurrent.futures import ProcessPoolExecutor, as_completed

        results: list[ProcessingResult] = []
        args_list = [(str(p),) for p, _ in to_process]
        key_map = {str(p): k for p, k in to_process}

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )

        with progress:
            task = progress.add_task("Document conversion", total=len(to_process))

            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(_process_single_markitdown, args): args
                    for args in args_list
                }

                for future in as_completed(future_map):
                    args = future_map[future]
                    try:
                        result = future.result()
                        results.append(result)
                        file_key = key_map[args[0]]
                        out_path = output_dir / f"{file_key}.json"
                        out_path.write_text(
                            result.model_dump_json(indent=2), encoding="utf-8"
                        )
                    except Exception as exc:
                        logger.error("markitdown failed for %s: %s", args[0], exc)
                    progress.advance(task)

        return results

    def _process_sequential(
        self,
        to_process: list[tuple[Path, str]],
        output_dir: Path,
    ) -> list[ProcessingResult]:
        """Process files sequentially with progress bar."""
        results: list[ProcessingResult] = []

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )

        with progress:
            task = progress.add_task("Document conversion", total=len(to_process))
            for file_path, file_key in to_process:
                progress.update(task, description=f"Convert: {file_path.name[:40]}")
                result = self.process_file(file_path)
                results.append(result)

                out_path = output_dir / f"{file_key}.json"
                out_path.write_text(
                    result.model_dump_json(indent=2), encoding="utf-8"
                )
                progress.advance(task)

        return results
