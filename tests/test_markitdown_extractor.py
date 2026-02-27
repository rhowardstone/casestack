"""Tests for the markitdown document processor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from casestack.models.document import ProcessingResult
from casestack.processors.markitdown_extractor import (
    MARKITDOWN_EXTENSIONS,
    _process_single_markitdown,
)
from casestack.processors.transcription import MEDIA_EXTENSIONS


# ---------------------------------------------------------------------------
# Tests: extension sets
# ---------------------------------------------------------------------------


class TestExtensions:
    def test_expected_types_present(self):
        expected = {".docx", ".xlsx", ".pptx", ".html", ".csv", ".txt", ".md", ".png"}
        assert expected.issubset(MARKITDOWN_EXTENSIONS)

    def test_no_overlap_with_pdf(self):
        assert ".pdf" not in MARKITDOWN_EXTENSIONS

    def test_no_overlap_with_media(self):
        overlap = MARKITDOWN_EXTENSIONS & MEDIA_EXTENSIONS
        assert overlap == set(), f"Unexpected overlap: {overlap}"


# ---------------------------------------------------------------------------
# Tests: _process_single_markitdown
# ---------------------------------------------------------------------------


class TestProcessSingle:
    def test_txt_file(self, tmp_path: Path):
        """Plain .txt should produce a document and one page."""
        txt = tmp_path / "hello.txt"
        txt.write_text("Hello world from a text file.", encoding="utf-8")

        # Mock markitdown to avoid needing it installed
        mock_result = MagicMock()
        mock_result.text_content = "Hello world from a text file."
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result
        mock_mid = MagicMock()
        mock_mid.MarkItDown.return_value = mock_converter

        with patch.dict("sys.modules", {"markitdown": mock_mid}):
            result = _process_single_markitdown((str(txt),))

        assert result.errors == []
        assert result.document is not None
        assert result.document.ocrText == "Hello world from a text file."
        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1
        assert result.pages[0].char_count == len("Hello world from a text file.")

    def test_docx_mocked(self, tmp_path: Path):
        """A mocked .docx should produce a document with markitdown tag."""
        docx = tmp_path / "report.docx"
        docx.write_bytes(b"\x00" * 50)

        mock_result = MagicMock()
        mock_result.text_content = "Report contents from docx."
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result
        mock_mid = MagicMock()
        mock_mid.MarkItDown.return_value = mock_converter

        with patch.dict("sys.modules", {"markitdown": mock_mid}):
            result = _process_single_markitdown((str(docx),))

        assert result.errors == []
        assert result.document is not None
        assert "markitdown" in result.document.tags
        assert result.document.ocrText == "Report contents from docx."

    def test_output_shape(self, tmp_path: Path):
        """ProcessingResult should have expected fields."""
        txt = tmp_path / "shape.txt"
        txt.write_text("content", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.text_content = "content"
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result
        mock_mid = MagicMock()
        mock_mid.MarkItDown.return_value = mock_converter

        with patch.dict("sys.modules", {"markitdown": mock_mid}):
            result = _process_single_markitdown((str(txt),))

        assert isinstance(result, ProcessingResult)
        assert result.source_path == str(txt)
        assert result.processing_time_ms >= 0
        assert isinstance(result.pages, list)
        assert isinstance(result.errors, list)
        assert isinstance(result.warnings, list)

    def test_graceful_skip_when_not_installed(self, tmp_path: Path):
        """Should return error result when markitdown is not installed."""
        txt = tmp_path / "no_markitdown.txt"
        txt.write_text("some text", encoding="utf-8")

        with patch.dict("sys.modules", {"markitdown": None}):
            result = _process_single_markitdown((str(txt),))

        assert len(result.errors) == 1
        assert "markitdown not installed" in result.errors[0]
        assert result.document is None
        assert result.pages == []

    def test_empty_output_produces_warning(self, tmp_path: Path):
        """Empty markitdown output should produce a warning, not an error."""
        txt = tmp_path / "empty.txt"
        txt.write_text("   ", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.text_content = ""
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result
        mock_mid = MagicMock()
        mock_mid.MarkItDown.return_value = mock_converter

        with patch.dict("sys.modules", {"markitdown": mock_mid}):
            result = _process_single_markitdown((str(txt),))

        assert result.errors == []
        assert any("empty text" in w for w in result.warnings)
        # Stub document still created (no errors)
        assert result.document is not None
        assert result.document.ocrText is None


# ---------------------------------------------------------------------------
# Tests: resume / batch
# ---------------------------------------------------------------------------


class TestBatchResume:
    def test_resume_skips_existing(self, tmp_path: Path):
        """Files with existing output JSON should be skipped (not reprocessed)."""
        from casestack.config import Settings

        settings = Settings(output_dir=tmp_path / "output")
        ocr_dir = tmp_path / "output" / "ocr"
        ocr_dir.mkdir(parents=True)

        # Create a file to process
        txt = tmp_path / "already.txt"
        txt.write_text("already done", encoding="utf-8")

        # Pre-create the output
        existing = ProcessingResult(
            source_path=str(txt),
            processing_time_ms=42,
            errors=[],
        )
        (ocr_dir / "already.json").write_text(
            existing.model_dump_json(indent=2), encoding="utf-8"
        )

        from casestack.processors.markitdown_extractor import MarkitdownProcessor

        proc = MarkitdownProcessor(settings)
        results = proc.process_batch([txt], ocr_dir, max_workers=1)

        # Skipped files are not returned — only newly processed ones
        assert len(results) == 0

    def test_serialization_roundtrip(self, tmp_path: Path):
        """ProcessingResult from markitdown should survive JSON roundtrip."""
        txt = tmp_path / "roundtrip.txt"
        txt.write_text("roundtrip content", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.text_content = "roundtrip content"
        mock_converter = MagicMock()
        mock_converter.convert.return_value = mock_result
        mock_mid = MagicMock()
        mock_mid.MarkItDown.return_value = mock_converter

        with patch.dict("sys.modules", {"markitdown": mock_mid}):
            result = _process_single_markitdown((str(txt),))

        json_str = result.model_dump_json()
        restored = ProcessingResult.model_validate_json(json_str)
        assert restored.source_path == result.source_path
        assert restored.document is not None
        assert restored.document.ocrText == "roundtrip content"
