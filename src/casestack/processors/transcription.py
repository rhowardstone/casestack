"""Audio/video transcription processor using faster-whisper."""

from __future__ import annotations

import hashlib
import json
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
from casestack.models.document import Document, Page, TranscriptionResult
from casestack.models.forensics import Transcript, TranscriptSegment

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v", ".vob", ".ts"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


def _detect_hardware() -> tuple[str, str, str]:
    """Detect available hardware and return (device, compute_type, model_size).

    Returns ``("cuda", "float16", "large-v3")`` when a CUDA GPU is available,
    otherwise ``("cpu", "int8", "tiny")``.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16", "large-v3"
    except ImportError:
        pass
    return "cpu", "int8", "tiny"


def _process_single_transcription(
    args: tuple[str, str, str, str],
) -> TranscriptionResult:
    """Transcribe a single audio/video file.

    Module-level function so it can be pickled if needed.
    Accepts ``(file_path, whisper_model, device, compute_type)``.
    """
    file_path_str, whisper_model, device, compute_type = args
    path = Path(file_path_str)
    start_ms = time.monotonic_ns() // 1_000_000
    errors: list[str] = []
    warnings: list[str] = []

    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    doc_id = f"transcript-{content_hash[:12]}"

    transcript_obj: Transcript | None = None
    document: Document | None = None
    page_objects: list[Page] = []

    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(whisper_model, device=device, compute_type=compute_type)
        segments_iter, info = model.transcribe(str(path), beam_size=5)

        segments: list[TranscriptSegment] = []
        full_text_parts: list[str] = []

        for seg in segments_iter:
            segments.append(
                TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip())
            )
            full_text_parts.append(seg.text.strip())

        full_text = " ".join(full_text_parts)

        if not full_text.strip():
            warnings.append(f"Whisper produced empty transcript for {path.name}")
        else:
            transcript_obj = Transcript(
                source_path=str(path),
                document_id=doc_id,
                text=full_text,
                language=info.language or "en",
                duration_seconds=info.duration,
                segments=segments,
            )

            document = Document(
                id=doc_id,
                title=path.stem.replace("_", " ").replace("-", " ").strip(),
                source="local",
                category="media",
                ocrText=full_text,
                tags=["transcript"],
            )

            # Create pages from transcript segments (group ~30s chunks)
            _CHUNK_SECONDS = 30.0
            current_text_parts: list[str] = []
            chunk_start = 0.0
            page_num = 1

            for seg in segments:
                current_text_parts.append(seg.text)
                if seg.end - chunk_start >= _CHUNK_SECONDS:
                    page_text = " ".join(current_text_parts)
                    page_objects.append(
                        Page(
                            document_id=doc_id,
                            page_number=page_num,
                            text_content=page_text,
                            char_count=len(page_text),
                        )
                    )
                    page_num += 1
                    current_text_parts = []
                    chunk_start = seg.end

            # Flush remaining
            if current_text_parts:
                page_text = " ".join(current_text_parts)
                page_objects.append(
                    Page(
                        document_id=doc_id,
                        page_number=page_num,
                        text_content=page_text,
                        char_count=len(page_text),
                    )
                )

    except ImportError:
        errors.append(
            "faster-whisper not installed. Install with: pip install 'casestack[transcription]'"
        )
    except Exception as exc:
        errors.append(f"Transcription failed for {path.name}: {exc}")

    elapsed = (time.monotonic_ns() // 1_000_000) - start_ms
    return TranscriptionResult(
        source_path=str(path),
        transcript=transcript_obj,
        document=document,
        pages=page_objects,
        processing_time_ms=elapsed,
        errors=errors,
        warnings=warnings,
    )


class TranscriptionProcessor:
    """Process audio/video files through Whisper transcription."""

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.device, self.compute_type, self._auto_model = _detect_hardware()

        # Use configured model or auto-detect
        if config.whisper_model and config.whisper_model != "auto":
            self.whisper_model = config.whisper_model
        else:
            self.whisper_model = self._auto_model

        # Allow explicit device override
        if config.whisper_device and config.whisper_device != "auto":
            self.device = config.whisper_device

        logger.info(
            "Transcription: model=%s device=%s compute=%s",
            self.whisper_model,
            self.device,
            self.compute_type,
        )

    def process_file(self, path: Path) -> TranscriptionResult:
        """Transcribe a single audio/video file."""
        return _process_single_transcription(
            (str(path), self.whisper_model, self.device, self.compute_type)
        )

    def process_batch(
        self,
        paths: list[Path],
        output_dir: Path,
        max_workers: int = 1,
    ) -> list[TranscriptionResult]:
        """Process multiple media files sequentially (GPU memory constraint).

        Files whose output JSON already exists are skipped (resumable).
        """
        transcripts_dir = output_dir / "transcripts"
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        results: list[TranscriptionResult] = []

        # Filename-based resume check
        existing = set(f.stem for f in transcripts_dir.glob("*.json"))
        to_process: list[tuple[Path, str]] = []
        for p in paths:
            name_key = p.stem
            if name_key in existing:
                out_path = transcripts_dir / f"{name_key}.json"
                try:
                    prev = TranscriptionResult.model_validate_json(
                        out_path.read_text(encoding="utf-8")
                    )
                    results.append(prev)
                except Exception:
                    to_process.append((p, name_key))
            else:
                to_process.append((p, name_key))

        if not to_process:
            return results

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )

        with progress:
            task = progress.add_task("Transcribing", total=len(to_process))
            for file_path, file_key in to_process:
                progress.update(task, description=f"Transcribe: {file_path.name[:40]}")
                result = self.process_file(file_path)
                results.append(result)

                out_path = transcripts_dir / f"{file_key}.json"
                out_path.write_text(
                    result.model_dump_json(indent=2), encoding="utf-8"
                )
                progress.advance(task)

        return results
