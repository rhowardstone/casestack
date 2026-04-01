"""Regression tests for the markitdown document processor.

Covers:
- Extension set correctness (no images, no PDFs, no media overlap)
- _chunk_text() pagination logic
- _content_key() collision-free resume keys
- process_single_image_stub() for standalone images
- _process_single_markitdown() end-to-end with mocked markitdown
- MarkitdownProcessor.process_batch() resume behaviour
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from casestack.models.document import ProcessingResult
from casestack.processors.markitdown_extractor import (
    IMAGE_EXTENSIONS,
    MARKITDOWN_EXTENSIONS,
    _chunk_text,
    _content_key,
    _process_single_markitdown,
    process_single_image_stub,
)
from casestack.processors.transcription import MEDIA_EXTENSIONS


# ---------------------------------------------------------------------------
# Extension set correctness
# ---------------------------------------------------------------------------


class TestExtensions:
    def test_office_types_present(self):
        assert {".docx", ".xlsx", ".xls", ".pptx"}.issubset(MARKITDOWN_EXTENSIONS)

    def test_web_data_types_present(self):
        assert {".html", ".htm", ".csv", ".json"}.issubset(MARKITDOWN_EXTENSIONS)

    def test_text_types_present(self):
        assert {".txt", ".md"}.issubset(MARKITDOWN_EXTENSIONS)

    def test_pdf_not_in_markitdown(self):
        """PDFs have their own OCR step — must not be in markitdown set."""
        assert ".pdf" not in MARKITDOWN_EXTENSIONS

    def test_images_not_in_markitdown(self):
        """Images were previously in MARKITDOWN_EXTENSIONS (bug). Regression test."""
        image_exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"}
        overlap = MARKITDOWN_EXTENSIONS & image_exts
        assert overlap == set(), (
            f"Image extensions must not be in MARKITDOWN_EXTENSIONS: {overlap}"
        )

    def test_no_overlap_with_media(self):
        """No audio/video extension should be in markitdown set."""
        overlap = MARKITDOWN_EXTENSIONS & MEDIA_EXTENSIONS
        assert overlap == set(), f"Unexpected overlap with MEDIA_EXTENSIONS: {overlap}"

    def test_image_extensions_defined(self):
        assert {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"}.issubset(IMAGE_EXTENSIONS)

    def test_image_extensions_not_in_media(self):
        """Image and media sets should be disjoint."""
        overlap = IMAGE_EXTENSIONS & MEDIA_EXTENSIONS
        assert overlap == set(), f"IMAGE_EXTENSIONS overlaps MEDIA_EXTENSIONS: {overlap}"

    def test_markitdown_is_frozen(self):
        """Extension sets should be immutable to prevent accidental mutation."""
        assert isinstance(MARKITDOWN_EXTENSIONS, frozenset)
        assert isinstance(IMAGE_EXTENSIONS, frozenset)


# ---------------------------------------------------------------------------
# _chunk_text() — pagination of long documents
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_short_text_single_page(self):
        """Text under _CHUNK_TARGET_CHARS should produce exactly one page."""
        text = "Short document content."
        pages = _chunk_text(text, "doc-001")
        assert len(pages) == 1
        assert pages[0].page_number == 1
        assert pages[0].text_content == text
        assert pages[0].document_id == "doc-001"

    def test_empty_text_returns_no_pages(self):
        pages = _chunk_text("", "doc-001")
        assert pages == []

    def test_whitespace_only_returns_no_pages(self):
        pages = _chunk_text("   \n\n   ", "doc-001")
        assert pages == []

    def test_long_text_produces_multiple_pages(self):
        """A 10KB document should be split into several pages."""
        # ~10 KB of text with paragraph breaks
        paragraphs = [f"Paragraph {i}: " + ("x" * 180) for i in range(50)]
        text = "\n\n".join(paragraphs)
        assert len(text) > 2000  # Ensure it's actually long

        pages = _chunk_text(text, "doc-long")
        assert len(pages) > 1, "Long document should produce multiple pages"

    def test_page_numbers_sequential(self):
        paragraphs = [f"Para {i}: " + ("word " * 40) for i in range(30)]
        text = "\n\n".join(paragraphs)
        pages = _chunk_text(text, "doc-seq")
        for i, page in enumerate(pages):
            assert page.page_number == i + 1

    def test_no_page_exceeds_double_target(self):
        """No individual page should be more than 2x the target size."""
        from casestack.processors.markitdown_extractor import _CHUNK_TARGET_CHARS
        paragraphs = ["word " * 30 for _ in range(60)]
        text = "\n\n".join(paragraphs)
        pages = _chunk_text(text, "doc-size")
        for page in pages:
            assert page.char_count <= _CHUNK_TARGET_CHARS * 2

    def test_char_counts_match_content(self):
        """char_count field must equal actual text_content length."""
        text = "\n\n".join([f"Content block {i}: " + "a" * 100 for i in range(20)])
        pages = _chunk_text(text, "doc-counts")
        for page in pages:
            assert page.char_count == len(page.text_content)

    def test_no_content_lost(self):
        """All non-whitespace content from input must appear in some page."""
        paras = [f"unique-marker-{i}" for i in range(30)]
        text = "\n\n".join(paras)
        pages = _chunk_text(text, "doc-nolose")
        combined = "\n".join(p.text_content for p in pages)
        for marker in paras:
            assert marker in combined, f"Content lost: {marker}"

    def test_exactly_at_target_size(self):
        """Text exactly at chunk target produces one page."""
        from casestack.processors.markitdown_extractor import _CHUNK_TARGET_CHARS
        text = "x" * _CHUNK_TARGET_CHARS
        pages = _chunk_text(text, "doc-exact")
        assert len(pages) == 1

    def test_document_id_propagated(self):
        text = "\n\n".join(["block " * 50] * 20)
        pages = _chunk_text(text, "my-doc-id")
        assert all(p.document_id == "my-doc-id" for p in pages)


# ---------------------------------------------------------------------------
# _content_key() — collision-free resume keys
# ---------------------------------------------------------------------------


class TestContentKey:
    def test_same_file_same_key(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("hello")
        assert _content_key(f) == _content_key(f)

    def test_different_paths_different_keys(self, tmp_path):
        """Two files with the same name in different directories must get different keys."""
        d1 = tmp_path / "subdir1"
        d2 = tmp_path / "subdir2"
        d1.mkdir(); d2.mkdir()
        (d1 / "notes.txt").write_text("a")
        (d2 / "notes.txt").write_text("a")

        k1 = _content_key(d1 / "notes.txt")
        k2 = _content_key(d2 / "notes.txt")
        assert k1 != k2, "Different paths must produce different resume keys"

    def test_key_is_short_string(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("x")
        key = _content_key(f)
        assert isinstance(key, str)
        assert 8 <= len(key) <= 32  # Reasonable length for a filename component


# ---------------------------------------------------------------------------
# process_single_image_stub()
# ---------------------------------------------------------------------------


class TestImageStub:
    def test_stub_creates_document(self, tmp_path):
        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        result = process_single_image_stub(img)

        assert result.errors == []
        assert result.document is not None
        assert result.document.id.startswith("img-")
        assert "image" in result.document.tags

    def test_stub_produces_one_page(self, tmp_path):
        img = tmp_path / "scan.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)

        result = process_single_image_stub(img)
        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1
        assert img.name in result.pages[0].text_content

    def test_stub_has_warning_not_error(self, tmp_path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"\x00" * 10)

        result = process_single_image_stub(img)
        assert result.errors == []
        assert len(result.warnings) >= 1
        assert any("stub" in w.lower() or "caption" in w.lower() for w in result.warnings)

    def test_stub_title_from_filename(self, tmp_path):
        img = tmp_path / "witness_photo_001.png"
        img.write_bytes(b"\x00" * 10)

        result = process_single_image_stub(img)
        assert result.document is not None
        # Stem with underscores replaced by spaces
        assert "witness" in result.document.title.lower()

    def test_stub_source_path_correct(self, tmp_path):
        img = tmp_path / "evidence.png"
        img.write_bytes(b"\x00" * 10)

        result = process_single_image_stub(img)
        assert result.source_path == str(img)


# ---------------------------------------------------------------------------
# _process_single_markitdown() — end-to-end with mocked markitdown
# ---------------------------------------------------------------------------


def _mock_markitdown(text_content: str):
    """Helper to create a markitdown module mock returning given text."""
    mock_result = MagicMock()
    mock_result.text_content = text_content
    mock_converter = MagicMock()
    mock_converter.convert.return_value = mock_result
    mock_mid = MagicMock()
    mock_mid.MarkItDown.return_value = mock_converter
    return mock_mid


class TestProcessSingle:
    def test_txt_file_single_page(self, tmp_path):
        txt = tmp_path / "hello.txt"
        txt.write_text("Hello world from a text file.", encoding="utf-8")

        with patch.dict("sys.modules", {"markitdown": _mock_markitdown("Hello world from a text file.")}):
            result = _process_single_markitdown((str(txt),))

        assert result.errors == []
        assert result.document is not None
        assert result.document.ocrText == "Hello world from a text file."
        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1

    def test_long_document_multi_page(self, tmp_path):
        """Documents exceeding chunk target must produce multiple pages."""
        big_content = "\n\n".join([f"Section {i}: " + "word " * 50 for i in range(40)])
        assert len(big_content) > 2000

        docx = tmp_path / "report.docx"
        docx.write_bytes(b"\x00" * 50)

        with patch.dict("sys.modules", {"markitdown": _mock_markitdown(big_content)}):
            result = _process_single_markitdown((str(docx),))

        assert result.errors == []
        assert result.document is not None
        assert len(result.pages) > 1, "Long document must be chunked into multiple pages"

    def test_tags_include_extension(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_bytes(b"a,b,c")

        with patch.dict("sys.modules", {"markitdown": _mock_markitdown("a,b,c\n1,2,3")}):
            result = _process_single_markitdown((str(csv_file),))

        assert result.document is not None
        assert "csv" in result.document.tags
        assert "markitdown" in result.document.tags

    def test_docx_mocked(self, tmp_path):
        docx = tmp_path / "report.docx"
        docx.write_bytes(b"\x00" * 50)

        with patch.dict("sys.modules", {"markitdown": _mock_markitdown("Report contents from docx.")}):
            result = _process_single_markitdown((str(docx),))

        assert result.errors == []
        assert result.document is not None
        assert "markitdown" in result.document.tags

    def test_graceful_skip_when_not_installed(self, tmp_path):
        txt = tmp_path / "no_markitdown.txt"
        txt.write_text("some text", encoding="utf-8")

        with patch.dict("sys.modules", {"markitdown": None}):
            result = _process_single_markitdown((str(txt),))

        assert len(result.errors) == 1
        assert "markitdown not installed" in result.errors[0]
        assert result.document is None
        assert result.pages == []

    def test_empty_output_produces_warning(self, tmp_path):
        txt = tmp_path / "empty.txt"
        txt.write_text("   ", encoding="utf-8")

        with patch.dict("sys.modules", {"markitdown": _mock_markitdown("")}):
            result = _process_single_markitdown((str(txt),))

        assert result.errors == []
        assert any("empty text" in w for w in result.warnings)
        assert result.document is not None
        assert result.document.ocrText is None

    def test_output_shape(self, tmp_path):
        txt = tmp_path / "shape.txt"
        txt.write_text("content", encoding="utf-8")

        with patch.dict("sys.modules", {"markitdown": _mock_markitdown("content")}):
            result = _process_single_markitdown((str(txt),))

        assert isinstance(result, ProcessingResult)
        assert result.source_path == str(txt)
        assert result.processing_time_ms >= 0
        assert isinstance(result.pages, list)
        assert isinstance(result.errors, list)
        assert isinstance(result.warnings, list)

    def test_doc_id_is_content_hash_based(self, tmp_path):
        """doc_id should be derived from file content, not filename."""
        f1 = tmp_path / "file_a.txt"
        f2 = tmp_path / "file_b.txt"
        f1.write_text("identical content", encoding="utf-8")
        f2.write_text("identical content", encoding="utf-8")

        mock = _mock_markitdown("identical content")
        with patch.dict("sys.modules", {"markitdown": mock}):
            r1 = _process_single_markitdown((str(f1),))
            r2 = _process_single_markitdown((str(f2),))

        assert r1.document.id == r2.document.id, "Same content → same doc_id"

    def test_serialization_roundtrip(self, tmp_path):
        txt = tmp_path / "roundtrip.txt"
        txt.write_text("roundtrip content", encoding="utf-8")

        with patch.dict("sys.modules", {"markitdown": _mock_markitdown("roundtrip content")}):
            result = _process_single_markitdown((str(txt),))

        json_str = result.model_dump_json()
        restored = ProcessingResult.model_validate_json(json_str)
        assert restored.source_path == result.source_path
        assert restored.document is not None
        assert restored.document.ocrText == "roundtrip content"


# ---------------------------------------------------------------------------
# MarkitdownProcessor.process_batch() — resume behaviour
# ---------------------------------------------------------------------------


class TestBatchResume:
    def test_resume_skips_existing_by_path_key(self, tmp_path):
        """Files whose key-based output JSON exists should be skipped."""
        from casestack.config import Settings
        from casestack.processors.markitdown_extractor import MarkitdownProcessor

        settings = Settings(output_dir=tmp_path / "output")
        ocr_dir = tmp_path / "output" / "ocr"
        ocr_dir.mkdir(parents=True)

        txt = tmp_path / "already.txt"
        txt.write_text("already done", encoding="utf-8")

        # Pre-create the output using the collision-free key
        key = _content_key(txt)
        existing = ProcessingResult(source_path=str(txt), processing_time_ms=42, errors=[])
        (ocr_dir / f"{key}.json").write_text(existing.model_dump_json(indent=2), encoding="utf-8")

        proc = MarkitdownProcessor(settings)
        results = proc.process_batch([txt], ocr_dir, max_workers=1)
        assert len(results) == 0  # Skipped, not reprocessed

    def test_same_stem_different_dirs_not_skipped(self, tmp_path):
        """Bug regression: two 'notes.txt' in different subdirs must both be processed."""
        from casestack.config import Settings
        from casestack.processors.markitdown_extractor import MarkitdownProcessor

        settings = Settings(output_dir=tmp_path / "output")
        ocr_dir = tmp_path / "output" / "ocr"
        ocr_dir.mkdir(parents=True)

        d1 = tmp_path / "dir1"; d1.mkdir()
        d2 = tmp_path / "dir2"; d2.mkdir()
        f1 = d1 / "notes.txt"; f1.write_text("content A")
        f2 = d2 / "notes.txt"; f2.write_text("content B")

        # Simulate only f1 having been processed
        key1 = _content_key(f1)
        existing = ProcessingResult(source_path=str(f1), processing_time_ms=1, errors=[])
        (ocr_dir / f"{key1}.json").write_text(existing.model_dump_json(indent=2), encoding="utf-8")

        proc = MarkitdownProcessor(settings)
        mock = _mock_markitdown("content B")
        with patch.dict("sys.modules", {"markitdown": mock}):
            results = proc.process_batch([f1, f2], ocr_dir, max_workers=1)

        # Only f2 should be processed (f1 was skipped via its distinct key)
        assert len(results) == 1
        assert results[0].source_path == str(f2)
