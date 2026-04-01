"""Universal document processor using Microsoft markitdown for text extraction."""

from __future__ import annotations

import hashlib
import logging
import re
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

# Extensions markitdown handles well — text/structured content.
# NOTE: image extensions (.png, .jpg, etc.) intentionally excluded; markitdown
# only extracts EXIF metadata from images which adds noise without value.
# Standalone images are handled by a dedicated stub/caption step in ingest.
MARKITDOWN_EXTENSIONS = frozenset({
    # Office / structured documents
    ".docx", ".xlsx", ".xls", ".pptx",
    # Web / data
    ".html", ".htm", ".csv",
    ".json", ".jsonl",
    # Other formats markitdown handles
    ".epub", ".zip", ".ipynb", ".msg",
    # NOTE: .eml files are handled by email_extractor.py (not markitdown) so
    # that we extract clean text + attachments instead of raw MIME blobs.
    # .eml is intentionally NOT listed here.
    # Plain text
    ".txt", ".md",
})

# Image extensions that need dedicated visual processing (not markitdown).
IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp", ".heic",
})

# Target chunk size for long documents (characters). Matches the FTS5 display
# limit in search_pages() so each chunk maps to roughly one "page" in search.
_CHUNK_TARGET_CHARS = 2000
_CHUNK_MIN_CHARS = 300  # Don't emit stubs smaller than this


def _chunk_text(text: str, doc_id: str) -> list[Page]:
    """Split long text into FTS5-friendly pages.

    Strategy (matches OCR's _split_docling_pages approach):
    1. Split on double newlines (paragraph breaks).
    2. Merge fragments until _CHUNK_TARGET_CHARS is reached.
    3. Always produce at least one page even for short text.

    This ensures a 200KB CSV becomes ~100 searchable pages rather than one
    unindexable blob.
    """
    if not text.strip():
        return []

    # Fast path: short document fits in one page
    if len(text) <= _CHUNK_TARGET_CHARS:
        return [Page(
            document_id=doc_id,
            page_number=1,
            text_content=text,
            char_count=len(text),
        )]

    raw_paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        candidate = (current + "\n\n" + para).strip() if current else para
        if current and len(candidate) > _CHUNK_TARGET_CHARS:
            # Current buffer is full — flush it
            if len(current) >= _CHUNK_MIN_CHARS:
                chunks.append(current)
            else:
                # Too small to stand alone — append to previous or carry forward
                if chunks:
                    chunks[-1] = chunks[-1] + "\n\n" + current
                else:
                    chunks.append(current)
            current = para
        else:
            current = candidate

    # Flush remainder
    if current.strip():
        if len(current) >= _CHUNK_MIN_CHARS or not chunks:
            chunks.append(current)
        else:
            chunks[-1] = chunks[-1] + "\n\n" + current

    if not chunks:
        # Fallback: single page
        return [Page(document_id=doc_id, page_number=1, text_content=text, char_count=len(text))]

    return [
        Page(
            document_id=doc_id,
            page_number=i + 1,
            text_content=chunk,
            char_count=len(chunk),
        )
        for i, chunk in enumerate(chunks)
    ]


_DATE_PATTERNS = [
    # Yahoo Mail HTML table: | Date: | Mon, 1/24/2014 10:08:18 PM |
    re.compile(r"\|\s*Date:\s*\|\s*(?:\w+,\s*)?(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE),
    # Yahoo Mail HTML table with UTC: | Date: | 4/16/2016 9:33:24 PM UTC |
    re.compile(r"\|\s*Date:\s*\|\s*(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE),
    # Email header: Date: Thu, 01 Jan 2015 ...
    re.compile(r"^Date:\s*(?:\w+,\s*)?(\d{1,2}\s+\w+\s+\d{4})", re.IGNORECASE | re.MULTILINE),
    # ISO-ish: Date: 2015-01-07
    re.compile(r"^Date:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE | re.MULTILINE),
]


def _extract_date_from_text(text: str) -> str | None:
    """Try to extract an ISO date string from converted document text."""
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        raw = m.group(1).strip()
        try:
            from dateutil import parser as _dp
            dt = _dp.parse(raw, dayfirst=False)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return None


def _fix_mojibake(text: str) -> str:
    """Fix cp1252-over-UTF-8 mojibake (e.g. â€‹ → U+200B).

    Applies a best-effort cp1252→UTF-8 round-trip. If the result is valid UTF-8
    with fewer replacement characters than the original, use it. Otherwise
    return the original unchanged.
    """
    try:
        fixed = text.encode("cp1252").decode("utf-8")
        if fixed.count("\ufffd") <= text.count("\ufffd"):
            return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return text


def _extract_title_from_text(text: str) -> str | None:
    """Try to extract subject/title from email-formatted text."""
    m = re.search(r"\|\s*Subject:\s*\|\s*(.+?)(?:\s*\||\n)", text, re.IGNORECASE)
    if m:
        return _fix_mojibake(m.group(1).strip())
    m = re.search(r"^Subject:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if m:
        return _fix_mojibake(m.group(1).strip())
    return None


def _content_key(path: Path) -> str:
    """Stable resume key: relative-path-safe stem + suffix hash.

    Using only path.stem causes collisions when two files share a name across
    subdirectories (e.g. docs/notes.docx vs attachments/notes.csv). We use
    a hash of the full absolute path as the key, which is deterministic and
    collision-free while remaining short.
    """
    return hashlib.md5(str(path.resolve()).encode()).hexdigest()[:16]


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
        extracted_date = _extract_date_from_text(md_text)
        extracted_title = _extract_title_from_text(md_text) if path.suffix.lower() in (".html", ".htm") else None
        document = Document(
            id=doc_id,
            title=extracted_title or path.stem.replace("_", " ").replace("-", " ").strip(),
            source="local",
            category="other",
            ocrText=md_text,
            date=extracted_date,
            tags=["markitdown", path.suffix.lstrip(".").lower()],
        )
        page_objects = _chunk_text(md_text, doc_id)
    elif not errors:
        # File produced no text but no errors either — create stub document
        document = Document(
            id=doc_id,
            title=path.stem.replace("_", " ").replace("-", " ").strip(),
            source="local",
            category="other",
            ocrText=None,
            tags=["markitdown", path.suffix.lstrip(".").lower()],
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


def process_single_image_stub(path: Path) -> ProcessingResult:
    """Create a stub ProcessingResult for a standalone image file.

    Does not attempt visual captioning (that requires a VLM). Creates a
    minimal document record so the image appears in the corpus index and
    can be associated with its filename/metadata.
    """
    start_ms = time.monotonic_ns() // 1_000_000
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    doc_id = f"img-{content_hash[:12]}"
    title = path.stem.replace("_", " ").replace("-", " ").strip()

    document = Document(
        id=doc_id,
        title=title,
        source="local",
        category="other",
        ocrText=f"[Image file: {path.name}]",
        tags=["image", path.suffix.lstrip(".").lower()],
    )
    page_objects = [Page(
        document_id=doc_id,
        page_number=1,
        text_content=f"[Image file: {path.name}]",
        char_count=len(path.name) + 14,
    )]

    elapsed = (time.monotonic_ns() // 1_000_000) - start_ms
    return ProcessingResult(
        source_path=str(path),
        document=document,
        pages=page_objects,
        errors=[],
        warnings=["Image stub only — no visual content extracted. Enable captioning for full analysis."],
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
        Uses a collision-free path-hash key instead of path.stem to avoid
        skipping distinct files that share the same filename across subdirs.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[ProcessingResult] = []

        existing = set(f.stem for f in output_dir.glob("*.json"))
        to_process: list[tuple[Path, str]] = []
        skipped = 0
        for p in paths:
            key = _content_key(p)
            if key in existing:
                skipped += 1
            else:
                to_process.append((p, key))

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
