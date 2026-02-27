"""Tests for the audio/video transcription processor."""

from __future__ import annotations

import json
import struct
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from casestack.models.document import TranscriptionResult
from casestack.processors.transcription import (
    MEDIA_EXTENSIONS,
    _check_audio_content,
    _detect_hardware,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def silent_wav(tmp_path: Path) -> Path:
    """Create a 1-second silent WAV file."""
    wav_path = tmp_path / "silent.wav"
    n_channels = 1
    sample_width = 2  # 16-bit
    framerate = 16000
    n_frames = framerate  # 1 second
    with wave.open(str(wav_path), "w") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(framerate)
        wf.writeframes(struct.pack(f"<{n_frames}h", *([0] * n_frames)))
    return wav_path


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    """Create a directory with various media file stubs."""
    media = tmp_path / "media"
    media.mkdir()
    for ext in (".mp3", ".wav", ".mp4", ".mov", ".pdf", ".txt"):
        (media / f"test{ext}").write_bytes(b"\x00" * 100)
    return media


# ---------------------------------------------------------------------------
# Tests: hardware detection
# ---------------------------------------------------------------------------


class TestDetectHardware:
    def test_returns_cpu_when_no_torch(self):
        with patch.dict("sys.modules", {"torch": None}):
            device, compute_type, model_size = _detect_hardware()
        assert device == "cpu"
        assert compute_type == "int8"
        assert model_size == "tiny"

    def test_returns_cpu_when_no_cuda(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": mock_torch}):
            device, compute_type, model_size = _detect_hardware()
        assert device == "cpu"
        assert compute_type == "int8"
        assert model_size == "tiny"

    def test_returns_cuda_when_available(self):
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": mock_torch}):
            device, compute_type, model_size = _detect_hardware()
        assert device == "cuda"
        assert compute_type == "float16"
        assert model_size == "large-v3"


# ---------------------------------------------------------------------------
# Tests: media file discovery
# ---------------------------------------------------------------------------


class TestMediaDiscovery:
    def test_audio_extensions_detected(self):
        audio = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac", ".wma"}
        assert audio.issubset(MEDIA_EXTENSIONS)

    def test_video_extensions_detected(self):
        video = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v", ".vob", ".ts"}
        assert video.issubset(MEDIA_EXTENSIONS)

    def test_non_media_not_included(self):
        assert ".pdf" not in MEDIA_EXTENSIONS
        assert ".txt" not in MEDIA_EXTENSIONS
        assert ".docx" not in MEDIA_EXTENSIONS

    def test_discover_media_files(self, media_dir: Path):
        found = [
            f for f in media_dir.rglob("*")
            if f.suffix.lower() in MEDIA_EXTENSIONS and f.is_file()
        ]
        # Should find .mp3, .wav, .mp4, .mov but NOT .pdf or .txt
        extensions = {f.suffix.lower() for f in found}
        assert ".mp3" in extensions
        assert ".wav" in extensions
        assert ".mp4" in extensions
        assert ".mov" in extensions
        assert ".pdf" not in extensions
        assert ".txt" not in extensions


# ---------------------------------------------------------------------------
# Tests: silence detection
# ---------------------------------------------------------------------------


class TestCheckAudioContent:
    def test_silent_wav_detected(self, silent_wav: Path):
        """A fully silent WAV should be detected as having no speech."""
        has_speech, duration, rms_db = _check_audio_content(str(silent_wav))
        assert has_speech is False
        assert rms_db < -40.0
        assert duration > 0.0

    def test_loud_wav_detected(self, tmp_path: Path):
        """A WAV with a loud tone should be detected as having content."""
        wav_path = tmp_path / "loud.wav"
        framerate = 16000
        n_frames = framerate  # 1 second
        # Generate a 440Hz sine wave at full amplitude
        import math

        samples = [int(32000 * math.sin(2 * math.pi * 440 * i / framerate)) for i in range(n_frames)]
        with wave.open(str(wav_path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(framerate)
            wf.writeframes(struct.pack(f"<{n_frames}h", *samples))

        has_speech, duration, rms_db = _check_audio_content(str(wav_path))
        assert has_speech is True
        assert rms_db > -40.0

    def test_no_audio_stream(self, tmp_path: Path):
        """A file with no audio stream returns False."""
        # Create an empty file that can't have an audio stream
        fake = tmp_path / "noaudio.txt"
        fake.write_bytes(b"\x00" * 100)
        has_speech, duration, rms_db = _check_audio_content(str(fake))
        # Should gracefully return True (fallback) since av.open will fail
        assert has_speech is True  # fallback: assume content on error

    def test_nonexistent_file(self, tmp_path: Path):
        """A missing file returns True (fallback) so Whisper can report the real error."""
        has_speech, duration, rms_db = _check_audio_content(str(tmp_path / "nope.wav"))
        assert has_speech is True  # fallback on error


class TestSilenceSkipping:
    def test_silent_file_skipped_with_warning(self, silent_wav: Path):
        """Silent files should be skipped with a warning, not sent to Whisper."""
        from casestack.processors.transcription import _process_single_transcription

        # No need to mock faster_whisper — silence check should skip before it's used
        result = _process_single_transcription(
            (str(silent_wav), "tiny", "cpu", "int8")
        )
        assert any("silent" in w.lower() or "Skipped" in w for w in result.warnings)
        assert result.document is not None
        assert "silent" in result.document.tags
        assert result.transcript is None
        assert result.errors == []

    def test_loud_file_proceeds_to_transcription(self, tmp_path: Path):
        """A file with audio content should proceed to Whisper (mocked)."""
        from casestack.processors.transcription import _process_single_transcription

        # Create a loud WAV
        import math

        wav_path = tmp_path / "loud.wav"
        framerate = 16000
        n_frames = framerate
        samples = [int(32000 * math.sin(2 * math.pi * 440 * i / framerate)) for i in range(n_frames)]
        with wave.open(str(wav_path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(framerate)
            wf.writeframes(struct.pack(f"<{n_frames}h", *samples))

        # Mock whisper so it doesn't need the real model
        mock_seg = MagicMock()
        mock_seg.start = 0.0
        mock_seg.end = 1.0
        mock_seg.text = " Hello"

        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 1.0

        mock_model_cls = MagicMock()
        mock_model_instance = MagicMock()
        mock_model_instance.transcribe.return_value = (iter([mock_seg]), mock_info)
        mock_model_cls.return_value = mock_model_instance

        mock_fw = MagicMock()
        mock_fw.WhisperModel = mock_model_cls

        with patch.dict("sys.modules", {"faster_whisper": mock_fw}):
            result = _process_single_transcription(
                (str(wav_path), "tiny", "cpu", "int8")
            )

        # Should have proceeded to Whisper — no silence warning
        assert not any("silent" in w.lower() or "Skipped" in w for w in result.warnings)
        assert result.document is not None
        assert result.transcript is not None


# ---------------------------------------------------------------------------
# Tests: TranscriptionResult model
# ---------------------------------------------------------------------------


class TestTranscriptionResult:
    def test_minimal_creation(self):
        result = TranscriptionResult(
            source_path="/tmp/test.wav",
            processing_time_ms=100,
        )
        assert result.source_path == "/tmp/test.wav"
        assert result.transcript is None
        assert result.document is None
        assert result.pages == []
        assert result.errors == []

    def test_serialization_roundtrip(self):
        result = TranscriptionResult(
            source_path="/tmp/test.mp3",
            processing_time_ms=500,
            errors=["test error"],
            warnings=["test warning"],
        )
        json_str = result.model_dump_json()
        restored = TranscriptionResult.model_validate_json(json_str)
        assert restored.source_path == result.source_path
        assert restored.errors == ["test error"]
        assert restored.warnings == ["test warning"]

    def test_with_document(self):
        from casestack.models.document import Document, Page

        doc = Document(
            id="transcript-abc123",
            title="test audio",
            source="local",
            category="media",
            ocrText="hello world",
            tags=["transcript"],
        )
        page = Page(
            document_id="transcript-abc123",
            page_number=1,
            text_content="hello world",
            char_count=11,
        )
        result = TranscriptionResult(
            source_path="/tmp/test.wav",
            document=doc,
            pages=[page],
            processing_time_ms=100,
        )
        assert result.document is not None
        assert result.document.id == "transcript-abc123"
        assert len(result.pages) == 1


# ---------------------------------------------------------------------------
# Tests: TranscriptionProcessor
# ---------------------------------------------------------------------------


class TestTranscriptionProcessor:
    def test_graceful_skip_when_faster_whisper_missing(self, silent_wav: Path):
        """Processor should return an error result when faster-whisper is not installed."""
        from casestack.processors.transcription import _process_single_transcription

        with patch(
            "casestack.processors.transcription._check_audio_content",
            return_value=(True, 1.0, -10.0),
        ), patch.dict("sys.modules", {"faster_whisper": None}):
            result = _process_single_transcription(
                (str(silent_wav), "tiny", "cpu", "int8")
            )
        assert len(result.errors) == 1
        assert "faster-whisper not installed" in result.errors[0]
        assert result.document is None
        assert result.transcript is None

    def test_process_with_mocked_whisper(self, silent_wav: Path):
        """Processor should produce a transcript with mocked whisper output."""
        from casestack.processors.transcription import _process_single_transcription

        # Mock segment objects
        mock_seg1 = MagicMock()
        mock_seg1.start = 0.0
        mock_seg1.end = 1.5
        mock_seg1.text = " Hello world"

        mock_seg2 = MagicMock()
        mock_seg2.start = 1.5
        mock_seg2.end = 3.0
        mock_seg2.text = " This is a test"

        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 3.0

        mock_model_cls = MagicMock()
        mock_model_instance = MagicMock()
        mock_model_instance.transcribe.return_value = (
            iter([mock_seg1, mock_seg2]),
            mock_info,
        )
        mock_model_cls.return_value = mock_model_instance

        mock_fw = MagicMock()
        mock_fw.WhisperModel = mock_model_cls

        with patch(
            "casestack.processors.transcription._check_audio_content",
            return_value=(True, 3.0, -10.0),
        ), patch.dict("sys.modules", {"faster_whisper": mock_fw}):
            result = _process_single_transcription(
                (str(silent_wav), "tiny", "cpu", "int8")
            )

        assert result.errors == []
        assert result.document is not None
        assert "Hello world" in result.document.ocrText
        assert result.transcript is not None
        assert result.transcript.language == "en"
        assert len(result.transcript.segments) == 2
        assert len(result.pages) >= 1

    def test_resume_skips_existing(self, silent_wav: Path, tmp_path: Path):
        """Files with existing output JSON should be skipped (not reprocessed)."""
        from casestack.config import Settings

        settings = Settings(
            output_dir=tmp_path / "output",
            whisper_model="tiny",
            whisper_device="cpu",
        )

        # Pre-create the output file
        transcripts_dir = settings.output_dir / "transcripts"
        transcripts_dir.mkdir(parents=True)
        existing = TranscriptionResult(
            source_path=str(silent_wav),
            processing_time_ms=50,
        )
        (transcripts_dir / f"{silent_wav.stem}.json").write_text(
            existing.model_dump_json(indent=2), encoding="utf-8"
        )

        from casestack.processors.transcription import TranscriptionProcessor

        with patch(
            "casestack.processors.transcription._detect_hardware",
            return_value=("cpu", "int8", "tiny"),
        ):
            proc = TranscriptionProcessor(settings)
            results = proc.process_batch([silent_wav], settings.output_dir)

        # Skipped files are not returned — only newly processed ones
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Tests: FTS5 on transcripts
# ---------------------------------------------------------------------------


class TestTranscriptsFTS:
    def test_transcripts_fts_searchable(self, tmp_path: Path):
        """Transcripts should be searchable via transcripts_fts."""
        import sqlite3

        from casestack.exporters.sqlite_export import SqliteExporter
        from casestack.models.forensics import Transcript

        db_path = tmp_path / "test.db"
        transcript = Transcript(
            source_path="/tmp/audio.mp3",
            document_id="transcript-abc123",
            text="The quick brown fox jumps over the lazy dog",
            language="en",
            duration_seconds=5.0,
        )

        exporter = SqliteExporter()
        exporter.export(
            documents=[],
            persons=[],
            db_path=db_path,
            transcripts=[transcript],
        )

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT * FROM transcripts_fts WHERE transcripts_fts MATCH 'fox'",
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert "fox" in rows[0][0]
